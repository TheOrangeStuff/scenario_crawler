"""Compare profiler call data against a codebase directory.

Scans a directory tree for .m files and cross-references them with
profiler data to determine which functions were called and which were not.
"""

from dataclasses import dataclass
from pathlib import Path

from .parse_profiler_phases import CallEvent


@dataclass
class CoverageEntry:
    """Coverage status for a single codebase function."""
    name: str
    file: str
    called: bool
    call_count: int


@dataclass
class CoverageResult:
    """Result of codebase coverage analysis."""
    codebase_functions: list[str]
    codebase_files: list[str]
    called_functions: list[str]
    uncalled_functions: list[str]
    uncalled_files: list[str]
    coverage_percent: float
    entries: list[CoverageEntry]


def scan_codebase_coverage(
    codebase_dir: str | Path,
    call_sequence: list[CallEvent],
    function_table: list[dict],
) -> CoverageResult:
    """Compare profiler data against a codebase directory.

    Args:
        codebase_dir: Root directory to scan for .m files.
        call_sequence: Call sequence from parse_profiler_phases (can be empty).
        function_table: FunctionTable from the profiler data.

    Returns:
        CoverageResult with per-function coverage information.
    """
    codebase_dir = Path(codebase_dir)
    if not codebase_dir.is_dir():
        raise NotADirectoryError(f"Directory does not exist: {codebase_dir}")

    # Scan for all .m files
    m_files = sorted(codebase_dir.rglob("*.m"))

    codebase_funcs: list[str] = []
    codebase_files: list[str] = []
    for f in m_files:
        if f.is_file():
            codebase_funcs.append(f.stem)
            codebase_files.append(str(f))

    n_files = len(codebase_funcs)

    # Build set of functions from FunctionTable (all profiled functions)
    profiler_func_names: set[str] = set()
    if function_table:
        for entry in function_table:
            raw_name = str(entry.get("FunctionName", ""))
            # FunctionName may be like "path>funcName"
            parts = raw_name.split(">")
            base_name = parts[-1].split(".")[0]
            if base_name:
                profiler_func_names.add(base_name.lower())

    # Build call counts from call_sequence (phase-specific)
    phase_call_counts: dict[str, int] = {}
    if call_sequence:
        for ev in call_sequence:
            if ev.event == "enter":
                raw_name = ev.func_name
                parts = raw_name.split(">")
                base_name = parts[-1].split(".")[0]
                base_lower = base_name.lower()
                phase_call_counts[base_lower] = phase_call_counts.get(base_lower, 0) + 1

    # Compare
    called_mask = [False] * n_files
    call_counts = [0] * n_files

    for i, fname in enumerate(codebase_funcs):
        fname_lower = fname.lower()
        if fname_lower in profiler_func_names:
            called_mask[i] = True
        if fname_lower in phase_call_counts:
            call_counts[i] = phase_call_counts[fname_lower]

    called_funcs = [f for f, m in zip(codebase_funcs, called_mask) if m]
    uncalled_funcs = [f for f, m in zip(codebase_funcs, called_mask) if not m]
    uncalled_files_list = [
        f for f, m in zip(codebase_files, called_mask) if not m
    ]

    coverage_pct = (sum(called_mask) / n_files * 100) if n_files > 0 else 0.0

    entries = [
        CoverageEntry(
            name=codebase_funcs[i],
            file=codebase_files[i],
            called=called_mask[i],
            call_count=call_counts[i],
        )
        for i in range(n_files)
    ]
    # Sort: uncalled first, then by name
    entries.sort(key=lambda e: (e.called, e.name.lower()))

    return CoverageResult(
        codebase_functions=codebase_funcs,
        codebase_files=codebase_files,
        called_functions=called_funcs,
        uncalled_functions=uncalled_funcs,
        uncalled_files=uncalled_files_list,
        coverage_percent=coverage_pct,
        entries=entries,
    )
