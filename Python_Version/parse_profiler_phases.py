"""Parse MATLAB profiler .mat files and extract call sequences by phase range.

Loads a profiler .mat file (containing profile_info with FunctionTable and
FunctionHistory), detects phase boundaries via a configurable phase function
(default: 'phase_iterator'), and returns the call sequence for a requested
phase range.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import scipy.io as sio


@dataclass
class CallEvent:
    """A single enter/exit event in the call sequence."""
    index: int
    func_name: str
    file_name: str
    func_type: str
    depth: int
    event: str  # 'enter' or 'exit'
    hist_row: int


@dataclass
class PhaseParseResult:
    """Result of parsing profiler phases."""
    call_sequence: list[CallEvent]
    phase_indices: np.ndarray
    total_phases: int
    function_table: list[dict]
    raw_history: np.ndarray
    start_phase: int
    end_phase: int


def _extract_profile_info(data: dict) -> dict:
    """Find the profile_info struct in the loaded .mat data."""
    if "profile_info" in data:
        return data["profile_info"]

    # Search for any struct with FunctionTable and FunctionHistory
    for key, val in data.items():
        if key.startswith("__"):
            continue
        if isinstance(val, np.ndarray) and val.dtype.names:
            names = val.dtype.names
            if "FunctionTable" in names and "FunctionHistory" in names:
                return val
    raise ValueError(
        "Could not find profile_info with FunctionTable and "
        "FunctionHistory in the .mat file."
    )


def _unpack_struct_array(struct_arr):
    """Convert a MATLAB struct array loaded by scipy into a list of dicts."""
    # scipy.io.loadmat loads structs as numpy structured arrays
    # The shape can vary: (1,1), (1,N), or (N,)
    if isinstance(struct_arr, np.ndarray):
        if struct_arr.dtype.names is not None:
            # It's a structured array — flatten and iterate
            flat = struct_arr.flatten()
            if len(flat) == 1:
                return flat[0]
            return flat
    return struct_arr


def _get_field(struct_item, field_name, default=""):
    """Safely extract a field from a MATLAB struct item."""
    try:
        if isinstance(struct_item, np.void) and field_name in struct_item.dtype.names:
            val = struct_item[field_name]
            if isinstance(val, np.ndarray):
                val = val.flatten()
                if len(val) == 1:
                    val = val[0]
                if isinstance(val, np.ndarray) and val.size == 0:
                    return default
            if isinstance(val, (bytes, np.bytes_)):
                return val.decode("utf-8", errors="replace")
            if isinstance(val, np.str_):
                return str(val)
            return val if val is not None else default
        if hasattr(struct_item, field_name):
            return getattr(struct_item, field_name)
        if isinstance(struct_item, dict) and field_name in struct_item:
            return struct_item[field_name]
    except (KeyError, IndexError, TypeError):
        pass
    return default


def _build_function_table(raw_table) -> list[dict]:
    """Convert the raw FunctionTable into a list of dicts."""
    unpacked = _unpack_struct_array(raw_table)

    if isinstance(unpacked, np.void):
        # Single function entry
        return [{
            "FunctionName": _get_field(unpacked, "FunctionName", ""),
            "FileName": _get_field(unpacked, "FileName", ""),
            "Type": _get_field(unpacked, "Type", ""),
        }]

    table = []
    items = unpacked.flatten() if isinstance(unpacked, np.ndarray) else [unpacked]
    for item in items:
        entry = {
            "FunctionName": _get_field(item, "FunctionName", ""),
            "FileName": _get_field(item, "FileName", ""),
            "Type": _get_field(item, "Type", ""),
        }
        table.append(entry)
    return table


def parse_profiler_phases(
    mat_file: str | Path,
    start_phase: int,
    end_phase: int,
    *,
    hide_builtins: bool = False,
    hide_matlabroot: bool = False,
    exclude_names: Optional[list[str]] = None,
    phase_function: str = "phase_iterator",
    matlab_root: str = "",
) -> PhaseParseResult:
    """Parse a MATLAB profiler .mat file and extract call sequence for a phase range.

    Args:
        mat_file: Path to the profiler .mat file.
        start_phase: Starting phase number (1-indexed).
        end_phase: Ending phase number (1-indexed, inclusive).
        hide_builtins: Exclude functions with Type == 'Builtin'.
        hide_matlabroot: Exclude functions under matlab_root path.
        exclude_names: List of function names to exclude.
        phase_function: Name of the phase boundary function.
        matlab_root: Path prefix for matlabroot filtering.

    Returns:
        PhaseParseResult with the call sequence and metadata.
    """
    if exclude_names is None:
        exclude_names = []

    mat_file = Path(mat_file)
    if not mat_file.exists():
        raise FileNotFoundError(f"File not found: {mat_file}")

    # Load the .mat file
    data = sio.loadmat(str(mat_file), squeeze_me=True, struct_as_record=True)
    pinfo = _extract_profile_info(data)

    # Extract FunctionTable and FunctionHistory
    raw_func_table = _get_field(pinfo, "FunctionTable")
    func_history = np.atleast_2d(
        np.asarray(_get_field(pinfo, "FunctionHistory"), dtype=np.int64)
    )

    func_table = _build_function_table(raw_func_table)
    n_funcs = len(func_table)

    # Extract function names for matching
    func_names = [entry["FunctionName"] for entry in func_table]

    # Find the index(es) of phase_function in FunctionTable (1-indexed like MATLAB)
    phase_func_name_lower = phase_function.lower()
    phase_indices_in_table = []
    for i, name in enumerate(func_names):
        name_lower = str(name).lower()
        if name_lower == phase_func_name_lower:
            phase_indices_in_table.append(i + 1)  # 1-indexed
        else:
            # Check after '>' separator (e.g., "path>phase_iterator")
            parts = str(name).split(">")
            if any(p.strip().lower() == phase_func_name_lower for p in parts):
                phase_indices_in_table.append(i + 1)

    if not phase_indices_in_table:
        raise ValueError(
            f'Function "{phase_function}" not found in profiler data.'
        )

    # Find all rows where phase_function is entered (event == 0)
    phase_idx_set = set(phase_indices_in_table)
    is_phase_enter = (func_history[:, 0] == 0) & np.isin(
        func_history[:, 1], list(phase_idx_set)
    )
    phase_rows = np.where(is_phase_enter)[0]
    total_phases = len(phase_rows)

    if total_phases == 0:
        raise ValueError(
            f'No calls to "{phase_function}" found in FunctionHistory.'
        )

    # Validate range (1-indexed)
    if start_phase < 1 or start_phase > total_phases:
        raise ValueError(
            f"start_phase {start_phase} is out of range [1, {total_phases}]."
        )
    if end_phase < start_phase or end_phase > total_phases:
        raise ValueError(
            f"end_phase {end_phase} is out of range [{start_phase}, {total_phases}]."
        )

    # Determine the row range (0-indexed internally)
    row_start = phase_rows[start_phase - 1]
    if end_phase < total_phases:
        row_end = phase_rows[end_phase] - 1  # up to but not including next phase
    else:
        row_end = func_history.shape[0] - 1

    sub_history = func_history[row_start : row_end + 1, :]
    n_rows = sub_history.shape[0]

    # Build the call sequence with depth tracking
    exclude_lower = {n.lower() for n in exclude_names}
    depth = 0
    call_seq: list[CallEvent] = []
    seq_idx = 0

    for r in range(n_rows):
        event_code = int(sub_history[r, 0])
        f_idx = int(sub_history[r, 1])

        if f_idx < 1 or f_idx > n_funcs:
            continue

        entry = func_table[f_idx - 1]  # convert to 0-indexed
        f_name = str(entry["FunctionName"])
        f_file = str(entry.get("FileName", ""))
        f_type = str(entry.get("Type", ""))

        # Handle depth
        if event_code == 0:  # enter
            depth += 1
            event_str = "enter"
        else:  # exit
            event_str = "exit"

        # Apply filters
        skip = False
        if hide_builtins and f_type.lower() == "builtin":
            skip = True
        if hide_matlabroot and matlab_root and f_file.startswith(matlab_root):
            skip = True
        if f_name.lower() in exclude_lower:
            skip = True

        if not skip:
            seq_idx += 1
            call_seq.append(CallEvent(
                index=seq_idx,
                func_name=f_name,
                file_name=f_file,
                func_type=f_type,
                depth=depth,
                event=event_str,
                hist_row=int(row_start + r),
            ))

        if event_code == 1:  # exit
            depth = max(depth - 1, 0)

    return PhaseParseResult(
        call_sequence=call_seq,
        phase_indices=phase_rows,
        total_phases=total_phases,
        function_table=func_table,
        raw_history=func_history,
        start_phase=start_phase,
        end_phase=end_phase,
    )
