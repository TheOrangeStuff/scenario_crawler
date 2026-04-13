"""Stage 1 - Ingest and Index Building.

Scans a directory of zero-padded MATLAB profiler .mat files (v7.3 format),
parses FunctionHistory and FunctionTable from each, locates every occurrence
of LOOPER_FN, and writes a JSON index mapping each occurrence to its source
file and event position.
"""

import glob
import json
import os

import h5py
import numpy as np


LOOPER_FN = "LOOPER_FN"
INDEX_FILENAME = "looper_fn_index.json"


def _read_matlab_string(h5_ref, f):
    """Dereference an HDF5 object reference to extract a MATLAB string."""
    try:
        deref = f[h5_ref]
        raw = deref[()]
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        if isinstance(raw, np.ndarray):
            raw = raw.flatten()
            if raw.dtype.kind in ("U", "S", "O"):
                return "".join(chr(int(c)) for c in raw if int(c) != 0)
            if np.issubdtype(raw.dtype, np.integer) or np.issubdtype(raw.dtype, np.floating):
                return "".join(chr(int(c)) for c in raw if int(c) != 0)
        return str(raw)
    except Exception:
        return ""


def _parse_function_table(f, p_group):
    """Parse the FunctionTable from an HDF5 group representing the 'p' struct.

    Returns a list of dicts with keys 'FunctionName' and 'FileName'.
    """
    ft_ref = p_group["FunctionTable"]
    ft_group = f[ft_ref[0, 0]] if ft_ref.shape else f[ft_ref[()]]

    name_dataset = ft_group["FunctionName"]
    file_dataset = ft_group["FileName"]

    n_funcs = name_dataset.shape[1] if len(name_dataset.shape) > 1 else name_dataset.shape[0]

    table = []
    for i in range(n_funcs):
        if len(name_dataset.shape) > 1:
            name_ref = name_dataset[0, i]
            file_ref = file_dataset[0, i]
        else:
            name_ref = name_dataset[i]
            file_ref = file_dataset[i]

        func_name = _read_matlab_string(name_ref, f)
        file_name = _read_matlab_string(file_ref, f)
        table.append({"FunctionName": func_name, "FileName": file_name})

    return table


def _parse_function_history(f, p_group):
    """Parse the FunctionHistory 2xN matrix from an HDF5 group.

    Returns a numpy array of shape (2, N) where:
      Row 0 = event type (0=CALL, 1=RETURN)
      Row 1 = 1-based index into FunctionTable
    """
    fh_ref = p_group["FunctionHistory"]
    fh_data = fh_ref[()]

    if isinstance(fh_data, np.ndarray) and fh_data.ndim == 2:
        # HDF5/MATLAB stores column-major; h5py reads it transposed relative
        # to MATLAB convention.  MATLAB's 2xN becomes Nx2 or 2xN in h5py
        # depending on the version.  Normalise to 2xN.
        if fh_data.shape[0] == 2:
            return fh_data.astype(np.int64)
        if fh_data.shape[1] == 2:
            return fh_data.T.astype(np.int64)

    raise ValueError("FunctionHistory has unexpected shape: " + str(fh_data.shape))


def parse_mat_file(filepath):
    """Parse a single v7.3 .mat file.

    Returns (function_table, function_history) where function_history is 2xN.
    """
    with h5py.File(filepath, "r") as f:
        # The variable saved as 'p' contains the profile('info') struct
        if "p" not in f:
            raise KeyError(f"Variable 'p' not found in {filepath}. "
                           f"Available keys: {list(f.keys())}")
        p_group = f["p"]
        func_table = _parse_function_table(f, p_group)
        func_history = _parse_function_history(f, p_group)
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
