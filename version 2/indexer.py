"""Stage 1 - Ingest and Index Building.

Scans a directory of zero-padded MATLAB profiler .mat files, parses
FunctionHistory and FunctionTable from each, locates every occurrence
of LOOPER_FN, and writes a JSON index mapping each occurrence to its source
file and event position.
"""

import glob
import json
import os

import numpy as np
import scipy.io as sio


LOOPER_FN = "LOOPER_FN"
INDEX_FILENAME = "looper_fn_index.json"


# ---------------------------------------------------------------------------
# Numpy / scipy.io unwrapping helpers
# ---------------------------------------------------------------------------

def _unwrap_scalar(val):
    """Peel nested numpy wrappers until we reach a plain Python object.

    scipy.io.loadmat frequently returns values wrapped in one or more layers
    of numpy arrays, e.g. array([[array(['name'], dtype='<U4')]], dtype=object).
    This function drills through all of them transparently.
    """
    while isinstance(val, np.ndarray):
        if val.size == 0:
            return ""
        if val.size == 1:
            val = val.flat[0]
        else:
            break
    if isinstance(val, (bytes, np.bytes_)):
        return val.decode("utf-8", errors="replace")
    if isinstance(val, np.str_):
        return str(val)
    return val


def _get_field(struct_item, field_name, default=""):
    """Extract a named field from a scipy struct record (numpy.void)."""
    try:
        if isinstance(struct_item, np.void) and field_name in struct_item.dtype.names:
            return _unwrap_scalar(struct_item[field_name])
        if hasattr(struct_item, field_name):
            return _unwrap_scalar(getattr(struct_item, field_name))
        if isinstance(struct_item, dict) and field_name in struct_item:
            return _unwrap_scalar(struct_item[field_name])
    except (KeyError, IndexError, TypeError):
        pass
    return default


def _extract_p_struct(data):
    """Locate the profile-info struct inside the dict returned by loadmat.

    The MATLAB code saves ``p = profile('info')`` so the top-level key is
    ``'p'``.  After loadmat with ``squeeze_me=True`` this may be a
    ``numpy.void`` (the record itself) or still wrapped in one or two
    array dimensions — we normalise all variants here.
    """
    if "p" not in data:
        available = [k for k in data if not k.startswith("__")]
        raise KeyError(
            f"Variable 'p' not found in .mat file. "
            f"Available keys: {available}"
        )
    p = data["p"]
    # Strip surrounding array dimensions: (1,1) struct → scalar void
    while isinstance(p, np.ndarray) and p.dtype.names and p.size == 1:
        p = p.flat[0]
    return p


def _build_function_table(p_struct):
    """Convert the FunctionTable inside *p_struct* to a list of plain dicts.

    Each dict has keys ``'FunctionName'`` and ``'FileName'`` (Python str).
    """
    raw = _get_field(p_struct, "FunctionTable")

    # raw may be a structured array (N,) of records, or a single void record
    if isinstance(raw, np.void):
        return [{
            "FunctionName": str(_get_field(raw, "FunctionName", "")),
            "FileName":     str(_get_field(raw, "FileName", "")),
        }]

    if isinstance(raw, np.ndarray):
        items = raw.flatten()
    else:
        items = [raw]

    table = []
    for item in items:
        table.append({
            "FunctionName": str(_get_field(item, "FunctionName", "")),
            "FileName":     str(_get_field(item, "FileName", "")),
        })
    return table


def _build_function_history(p_struct):
    """Extract FunctionHistory from *p_struct* as a (2, N) int64 array.

    Row 0 = event type (0 = CALL, 1 = RETURN).
    Row 1 = 1-based index into FunctionTable.
    """
    raw = _get_field(p_struct, "FunctionHistory")
    fh = np.atleast_2d(np.asarray(raw, dtype=np.int64))

    # Normalise to shape (2, N) regardless of how scipy oriented it
    if fh.ndim == 2:
        if fh.shape[0] == 2:
            return fh
        if fh.shape[1] == 2:
            return fh.T

    raise ValueError("FunctionHistory has unexpected shape: " + str(fh.shape))


def parse_mat_file(filepath):
    """Parse a single .mat file via scipy.io.loadmat.

    Returns (function_table, function_history) where:
      function_table  – list[dict] with 'FunctionName' / 'FileName' strings
      function_history – numpy int64 array of shape (2, N)
    """
    data = sio.loadmat(str(filepath), squeeze_me=True, struct_as_record=True)
    p_struct = _extract_p_struct(data)
    func_table = _build_function_table(p_struct)
    func_history = _build_function_history(p_struct)
    return func_table, func_history


def find_mat_files(directory):
    """Find and return sorted list of .mat files in directory."""
    pattern = os.path.join(directory, "*.mat")
    files = sorted(glob.glob(pattern))
    return files


def build_index(mat_directory):
    """Build a LOOPER_FN occurrence index across all .mat files in a directory.

    Returns the index data (list of dicts) and also saves it as JSON.
    """
    mat_files = find_mat_files(mat_directory)
    if not mat_files:
        raise FileNotFoundError(f"No .mat files found in {mat_directory}")

    index_entries = []
    cumulative_occurrence = 0

    for mat_path in mat_files:
        mat_basename = os.path.basename(mat_path)
        func_table, func_history = parse_mat_file(mat_path)

        # Find indices in FunctionTable that correspond to LOOPER_FN
        looper_indices = set()
        for i, entry in enumerate(func_table):
            name = entry["FunctionName"]
            # Match exact name or after '>' separator (e.g. "path>LOOPER_FN")
            if name == LOOPER_FN:
                looper_indices.add(i + 1)  # 1-based as stored in FunctionHistory
            else:
                parts = name.split(">")
                if any(p.strip() == LOOPER_FN for p in parts):
                    looper_indices.add(i + 1)

        if not looper_indices:
            continue

        # Scan FunctionHistory for CALL events (row 0 == 0) to LOOPER_FN
        n_events = func_history.shape[1]
        for col in range(n_events):
            event_type = int(func_history[0, col])
            func_idx = int(func_history[1, col])
            if event_type == 0 and func_idx in looper_indices:
                cumulative_occurrence += 1
                index_entries.append({
                    "occurrence": cumulative_occurrence,
                    "mat_file": mat_basename,
                    "event_position": col,
                })

    # Save JSON index
    index_data = {"looper_fn_index": index_entries}
    index_path = os.path.join(mat_directory, INDEX_FILENAME)
    with open(index_path, "w") as fp:
        json.dump(index_data, fp, indent=2)

    return index_data, index_path, mat_files


def load_index(mat_directory):
    """Load an existing LOOPER_FN index JSON from the given directory."""
    index_path = os.path.join(mat_directory, INDEX_FILENAME)
    if not os.path.isfile(index_path):
        return None
    with open(index_path, "r") as fp:
        return json.load(fp)


def resolve_trace(func_table, func_history, max_rows=None):
    """Resolve a function history matrix into human-readable trace rows.

    Returns a list of dicts with keys: event, function_name, file_path.
    """
    n_events = func_history.shape[1]
    limit = min(n_events, max_rows) if max_rows else n_events
    rows = []
    for col in range(limit):
        event_type = int(func_history[0, col])
        func_idx = int(func_history[1, col])
        event_str = "CALL" if event_type == 0 else "RETURN"

        if 1 <= func_idx <= len(func_table):
            entry = func_table[func_idx - 1]
            func_name = entry["FunctionName"]
            file_path = entry["FileName"]
        else:
            func_name = f"<unknown index {func_idx}>"
            file_path = ""

        rows.append({
            "event": event_str,
            "function_name": func_name,
            "file_path": file_path,
        })
    return rows


def print_validation(mat_directory):
    """Run the indexer and print validation output to console."""
    print(f"Scanning directory: {mat_directory}")
    print("=" * 70)

    index_data, index_path, mat_files = build_index(mat_directory)

    # Summary
    print(f"Total .mat files found: {len(mat_files)}")
    print(f"Total LOOPER_FN occurrences found: {len(index_data['looper_fn_index'])}")
    print(f"Index file saved to: {index_path}")
    print()

    # Print first 20 rows of resolved trace from the first .mat file
    if mat_files:
        func_table, func_history = parse_mat_file(mat_files[0])
        trace_rows = resolve_trace(func_table, func_history, max_rows=20)
        print("First 20 rows of resolved trace:")
        print("-" * 70)
        print(f"{'EVENT':<10} {'FUNCTION_NAME':<30} {'FILE_PATH'}")
        print("-" * 70)
        for row in trace_rows:
            print(f"{row['event']:<10} {row['function_name']:<30} {row['file_path']}")

    print()
    print("Index building complete.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python indexer.py <directory_with_mat_files>")
        sys.exit(1)
    print_validation(sys.argv[1])
