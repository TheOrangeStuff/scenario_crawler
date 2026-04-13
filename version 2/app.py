"""MATLAB Profiler Trace Analyzer - Stages 2, 3, and 4.

A tkinter desktop application that:
  - Stage 2: Loads a sliced trace based on LOOPER_FN occurrence range (lazy loading)
  - Stage 3: Provides toggles (show built-ins, show RETURN events) and search
  - Stage 4: Opens a coverage window comparing trace against codebase .m files
"""

import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from indexer import (
    build_index,
    load_index,
    parse_mat_file,
    find_mat_files,
    LOOPER_FN,
    INDEX_FILENAME,
)


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _is_builtin(file_path, codebase_dir):
    """Return True if the function's file does NOT fall under codebase_dir."""
    if not codebase_dir or not file_path:
        return True
    try:
        return not os.path.normpath(file_path).startswith(
            os.path.normpath(codebase_dir)
        )
    except (TypeError, ValueError):
        return True


def _slice_trace(mat_directory, index_data, j, k, codebase_dir):
    """Load only the .mat files needed and slice trace from CALL of occurrence
    J to RETURN of occurrence K.

    Returns a list of dicts:
      {event, function_name, file_path, is_builtin}
    """
    entries = index_data["looper_fn_index"]

    # Entries for occurrences J..K (1-indexed)
    j_entry = None
    k_entry = None
    needed_files = set()

    for e in entries:
        occ = e["occurrence"]
        if occ == j:
            j_entry = e
        if occ == k:
            k_entry = e
        if j <= occ <= k:
            needed_files.add(e["mat_file"])

    if j_entry is None or k_entry is None:
        raise ValueError(f"Occurrences J={j} or K={k} not found in index.")

    # We also need any files between j's file and k's file (in sorted order)
    all_mats = find_mat_files(mat_directory)
    mat_basenames = [os.path.basename(m) for m in all_mats]

    j_file_idx = mat_basenames.index(j_entry["mat_file"])
    k_file_idx = mat_basenames.index(k_entry["mat_file"])

    for idx in range(j_file_idx, k_file_idx + 1):
        needed_files.add(mat_basenames[idx])

    # Load files in sorted order and concatenate traces
    ordered_files = [m for m in all_mats if os.path.basename(m) in needed_files]
    ordered_files.sort()

    # Build a combined trace across loaded files, tracking LOOPER_FN occurrences
    combined_rows = []
    looper_occurrence = 0

    # We need to know the global occurrence offset for files before j's file
    # Count LOOPER_FN occurrences in all files before the first needed file
    first_needed_idx = mat_basenames.index(os.path.basename(ordered_files[0]))
    for idx in range(first_needed_idx):
        mat_path = all_mats[idx]
        ft, fh = parse_mat_file(mat_path)
        looper_idxs = set()
        for i, entry in enumerate(ft):
            name = entry["FunctionName"]
            if name == LOOPER_FN or any(
                p.strip() == LOOPER_FN for p in name.split(">")
            ):
                looper_idxs.add(i + 1)
        if looper_idxs:
            n_events = fh.shape[1]
            for col in range(n_events):
                if int(fh[0, col]) == 0 and int(fh[1, col]) in looper_idxs:
                    looper_occurrence += 1

    # Now process the needed files
    slicing = False
    done = False

    for mat_path in ordered_files:
        if done:
            break

        ft, fh = parse_mat_file(mat_path)

        # Identify LOOPER_FN indices in this file's function table
        looper_idxs = set()
        for i, entry in enumerate(ft):
            name = entry["FunctionName"]
            if name == LOOPER_FN or any(
                p.strip() == LOOPER_FN for p in name.split(">")
            ):
                looper_idxs.add(i + 1)

        n_events = fh.shape[1]
        for col in range(n_events):
            event_type = int(fh[0, col])
            func_idx = int(fh[1, col])
            is_looper = func_idx in looper_idxs

            # Track LOOPER_FN CALL occurrences
            if is_looper and event_type == 0:
                looper_occurrence += 1
                if looper_occurrence == j:
                    slicing = True

            if slicing:
                if 1 <= func_idx <= len(ft):
                    entry = ft[func_idx - 1]
                    func_name = entry["FunctionName"]
                    file_path = entry["FileName"]
                else:
                    func_name = f"<unknown index {func_idx}>"
                    file_path = ""

                event_str = "CALL" if event_type == 0 else "RETURN"
                combined_rows.append({
                    "event": event_str,
                    "function_name": func_name,
                    "file_path": file_path,
                    "is_builtin": _is_builtin(file_path, codebase_dir),
                })

            # Stop after RETURN of LOOPER_FN occurrence K
            if is_looper and event_type == 1 and looper_occurrence == k:
                done = True
                break

    return combined_rows


# ---------------------------------------------------------------------------
# Coverage Window (Stage 4)
# ---------------------------------------------------------------------------

class CoverageWindow:
    """Separate tkinter Toplevel window showing .m file coverage."""

    def __init__(self, parent, codebase_dir, trace_rows):
        self.win = tk.Toplevel(parent)
        self.win.title("Coverage Analysis")
        self.win.geometry("800x600")
        self.win.minsize(500, 350)

        self.codebase_dir = codebase_dir
        self.trace_rows = trace_rows

        self._build_ui()
        self._compute_coverage()

    def _build_ui(self):
        # Summary label
        self.summary_var = tk.StringVar(value="Computing coverage...")
        ttk.Label(self.win, textvariable=self.summary_var,
                  font=("TkDefaultFont", 12, "bold")).pack(padx=10, pady=(10, 5), anchor="w")

        # Notebook with two tabs: Called and Uncalled
        self.notebook = ttk.Notebook(self.win)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Called tab
        called_frame = ttk.Frame(self.notebook)
        self.notebook.add(called_frame, text="Called .m Files")

        self.called_label_var = tk.StringVar()
        ttk.Label(called_frame, textvariable=self.called_label_var).pack(
            padx=5, pady=5, anchor="w")

        called_scroll = ttk.Scrollbar(called_frame, orient=tk.VERTICAL)
        self.called_listbox = tk.Listbox(called_frame,
                                         yscrollcommand=called_scroll.set,
                                         font=("Courier", 10))
        called_scroll.config(command=self.called_listbox.yview)
        self.called_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                                 padx=(5, 0), pady=5)
        called_scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 5), pady=5)

        # Uncalled tab
        uncalled_frame = ttk.Frame(self.notebook)
        self.notebook.add(uncalled_frame, text="Uncalled .m Files")

        self.uncalled_label_var = tk.StringVar()
        ttk.Label(uncalled_frame, textvariable=self.uncalled_label_var).pack(
            padx=5, pady=5, anchor="w")

        uncalled_scroll = ttk.Scrollbar(uncalled_frame, orient=tk.VERTICAL)
        self.uncalled_listbox = tk.Listbox(uncalled_frame,
                                           yscrollcommand=uncalled_scroll.set,
                                           font=("Courier", 10))
        uncalled_scroll.config(command=self.uncalled_listbox.yview)
        self.uncalled_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                                   padx=(5, 0), pady=5)
        uncalled_scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 5), pady=5)

    def _compute_coverage(self):
        # Walk codebase for all .m files
        all_m_files = set()
        for root, _dirs, files in os.walk(self.codebase_dir):
            for fname in files:
                if fname.endswith(".m"):
                    full = os.path.normpath(os.path.join(root, fname))
                    all_m_files.add(full)

        # Collect unique file paths from trace (non-builtin only)
        called_files = set()
        for row in self.trace_rows:
            if not row["is_builtin"] and row["file_path"]:
                normed = os.path.normpath(row["file_path"])
                if normed.endswith(".m"):
                    called_files.add(normed)

        called_m = all_m_files & called_files
        uncalled_m = all_m_files - called_files

        total = len(all_m_files)
        n_called = len(called_m)
        pct = (n_called / total * 100) if total > 0 else 0.0

        self.summary_var.set(f"Coverage: {pct:.1f}%  ({n_called} / {total} .m files called)")

        # Populate called list
        self.called_label_var.set(f"{n_called} called .m files:")
        for path in sorted(called_m):
            self.called_listbox.insert(tk.END, path)

        # Populate uncalled list
        self.uncalled_label_var.set(f"{len(uncalled_m)} uncalled .m files:")
        for path in sorted(uncalled_m):
            self.uncalled_listbox.insert(tk.END, path)


# ---------------------------------------------------------------------------
# Main Application Window (Stages 2, 3, 4)
# ---------------------------------------------------------------------------

class ProfilerTraceApp:
    """Main tkinter application for MATLAB profiler trace analysis."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("MATLAB Profiler Trace Analyzer")
        self.root.geometry("1100x700")
        self.root.minsize(800, 500)

        # State
        self.mat_directory = None
        self.codebase_dir = None
        self.index_data = None
        self.trace_rows = []          # Full sliced trace (all rows)
        self.visible_rows = []        # After applying toggles
        self.search_matches = []      # Indices into visible_rows
        self.search_index = 0

        self._build_ui()
        self.root.mainloop()

    # ── UI construction ─────────────────────────────────────────────

    def _build_ui(self):
        # --- Top row: directory inputs ---
        dir_frame = ttk.LabelFrame(self.root, text="Directories", padding=6)
        dir_frame.pack(fill=tk.X, padx=8, pady=(8, 4))

        ttk.Label(dir_frame, text=".mat Directory:").grid(
            row=0, column=0, sticky="w", padx=(0, 4))
        self.mat_dir_var = tk.StringVar()
        mat_dir_entry = ttk.Entry(dir_frame, textvariable=self.mat_dir_var, width=50)
        mat_dir_entry.grid(row=0, column=1, sticky="ew", padx=2)
        ttk.Button(dir_frame, text="Browse...",
                   command=self._browse_mat_dir).grid(row=0, column=2, padx=4)

        ttk.Label(dir_frame, text="Codebase Directory:").grid(
            row=1, column=0, sticky="w", padx=(0, 4), pady=(4, 0))
        self.codebase_dir_var = tk.StringVar()
        codebase_entry = ttk.Entry(dir_frame, textvariable=self.codebase_dir_var, width=50)
        codebase_entry.grid(row=1, column=1, sticky="ew", padx=2, pady=(4, 0))
        ttk.Button(dir_frame, text="Browse...",
                   command=self._browse_codebase_dir).grid(
            row=1, column=2, padx=4, pady=(4, 0))

        dir_frame.columnconfigure(1, weight=1)

        # --- Range + Analyze row ---
        range_frame = ttk.Frame(self.root, padding=4)
        range_frame.pack(fill=tk.X, padx=8)

        ttk.Label(range_frame, text="LOOPER_FN from occurrence:").pack(
            side=tk.LEFT, padx=(0, 4))

        self.j_var = tk.StringVar(value="1")
        j_spin = ttk.Spinbox(range_frame, from_=1, to=999999, width=7,
                              textvariable=self.j_var)
        j_spin.pack(side=tk.LEFT, padx=2)

        ttk.Label(range_frame, text="to:").pack(side=tk.LEFT, padx=4)

        self.k_var = tk.StringVar(value="2")
        k_spin = ttk.Spinbox(range_frame, from_=1, to=999999, width=7,
                              textvariable=self.k_var)
        k_spin.pack(side=tk.LEFT, padx=2)

        ttk.Button(range_frame, text="Analyze",
                   command=self._on_analyze).pack(side=tk.LEFT, padx=10)

        self.coverage_btn = ttk.Button(range_frame, text="Coverage",
                                       command=self._on_coverage,
                                       state=tk.DISABLED)
        self.coverage_btn.pack(side=tk.LEFT, padx=4)

        self.info_var = tk.StringVar(value="No data loaded.")
        ttk.Label(range_frame, textvariable=self.info_var).pack(
            side=tk.LEFT, padx=10)

        # --- Toggle + Search row (Stage 3) ---
        filter_frame = ttk.Frame(self.root, padding=4)
        filter_frame.pack(fill=tk.X, padx=8)

        self.show_builtins_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(filter_frame, text="Show built-ins",
                        variable=self.show_builtins_var,
                        command=self._apply_filters).pack(side=tk.LEFT, padx=4)

        self.show_returns_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(filter_frame, text="Show RETURN events",
                        variable=self.show_returns_var,
                        command=self._apply_filters).pack(side=tk.LEFT, padx=4)

        ttk.Separator(filter_frame, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Label(filter_frame, text="Search:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(filter_frame, textvariable=self.search_var,
                                 width=20)
        search_entry.pack(side=tk.LEFT, padx=4)
        search_entry.bind("<Return>", lambda _: self._on_search())

        ttk.Button(filter_frame, text="Find",
                   command=self._on_search).pack(side=tk.LEFT, padx=2)
        ttk.Button(filter_frame, text="< Prev",
                   command=self._on_search_prev).pack(side=tk.LEFT, padx=2)
        ttk.Button(filter_frame, text="Next >",
                   command=self._on_search_next).pack(side=tk.LEFT, padx=2)

        self.search_info_var = tk.StringVar()
        ttk.Label(filter_frame, textvariable=self.search_info_var).pack(
            side=tk.LEFT, padx=8)

        # --- Scrollable trace list ---
        list_frame = ttk.Frame(self.root)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 8))

        columns = ("seq", "event", "function", "file")
        self.tree = ttk.Treeview(list_frame, columns=columns,
                                 show="headings", selectmode="browse")
        self.tree.heading("seq", text="#")
        self.tree.heading("event", text="Event")
        self.tree.heading("function", text="Function Name")
        self.tree.heading("file", text="File Path")

        self.tree.column("seq", width=60, anchor="center")
        self.tree.column("event", width=70, anchor="center")
        self.tree.column("function", width=250)
        self.tree.column("file", width=450)

        yscroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,
                                command=self.tree.yview)
        xscroll = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL,
                                command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set,
                            xscrollcommand=xscroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

    # ── Directory browsing ──────────────────────────────────────────

    def _browse_mat_dir(self):
        path = filedialog.askdirectory(title="Select .mat File Directory")
        if path:
            self.mat_dir_var.set(path)

    def _browse_codebase_dir(self):
        path = filedialog.askdirectory(title="Select Codebase Directory")
        if path:
            self.codebase_dir_var.set(path)

    # ── Analyze (Stage 2) ──────────────────────────────────────────

    def _on_analyze(self):
        mat_dir = self.mat_dir_var.get().strip()
        codebase_dir = self.codebase_dir_var.get().strip()

        if not mat_dir or not os.path.isdir(mat_dir):
            messagebox.showerror("Error",
                                 "Please specify a valid .mat file directory.")
            return

        try:
            j = int(self.j_var.get())
            k = int(self.k_var.get())
        except ValueError:
            messagebox.showerror("Error",
                                 "J and K must be integers.")
            return

        if k <= j:
            messagebox.showwarning("Invalid Range",
                                   "K must be greater than J.")
            return

        self.mat_directory = mat_dir
        self.codebase_dir = codebase_dir if codebase_dir else None

        # Build or load index
        self.info_var.set("Building index...")
        self.root.update_idletasks()

        try:
            index = load_index(mat_dir)
            if index is None:
                index, _, _ = build_index(mat_dir)
            self.index_data = index
        except Exception as e:
            messagebox.showerror("Index Error", str(e))
            self.info_var.set("Index building failed.")
            return

        # Validate J, K against index
        total_occ = len(self.index_data["looper_fn_index"])
        if j < 1 or j > total_occ:
            messagebox.showerror("Error",
                                 f"J={j} is out of range [1, {total_occ}].")
            self.info_var.set("No data loaded.")
            return
        if k < 1 or k > total_occ:
            messagebox.showerror("Error",
                                 f"K={k} is out of range [1, {total_occ}].")
            self.info_var.set("No data loaded.")
            return

        # Slice the trace (lazy loading)
        self.info_var.set(f"Loading trace for occurrences {j}..{k}...")
        self.root.update_idletasks()

        try:
            self.trace_rows = _slice_trace(
                mat_dir, self.index_data, j, k, self.codebase_dir
            )
        except Exception as e:
            messagebox.showerror("Trace Error", str(e))
            self.info_var.set("Trace loading failed.")
            return

        self.info_var.set(
            f"Loaded {len(self.trace_rows)} events "
            f"(LOOPER_FN {j}..{k}, {total_occ} total occurrences)"
        )

        # Enable coverage button
        self.coverage_btn.config(state=tk.NORMAL)

        # Apply current filters and display
        self._apply_filters()

    # ── Filtering (Stage 3) ─────────────────────────────────────────

    def _apply_filters(self):
        """Recompute visible_rows based on toggle states, then refresh the tree."""
        show_builtins = self.show_builtins_var.get()
        show_returns = self.show_returns_var.get()

        self.visible_rows = []
        for row in self.trace_rows:
            if not show_builtins and row["is_builtin"]:
                continue
            if not show_returns and row["event"] == "RETURN":
                continue
            self.visible_rows.append(row)

        self._refresh_tree()

        # Clear search state when filters change
        self.search_matches = []
        self.search_index = 0
        self.search_info_var.set("")

    def _refresh_tree(self):
        """Clear and repopulate the treeview from visible_rows."""
        self.tree.delete(*self.tree.get_children())
        for i, row in enumerate(self.visible_rows):
            self.tree.insert("", tk.END, iid=str(i), values=(
                i + 1,
                row["event"],
                row["function_name"],
                row["file_path"],
            ))

    # ── Search (Stage 3) ───────────────────────────────────────────

    def _on_search(self):
        query = self.search_var.get().strip()
        if not query or not self.visible_rows:
            self.search_matches = []
            self.search_index = 0
            self.search_info_var.set("")
            return

        query_lower = query.lower()
        self.search_matches = [
            i for i, row in enumerate(self.visible_rows)
            if row["function_name"].lower() == query_lower
        ]

        n = len(self.search_matches)
        if n == 0:
            self.search_index = 0
            self.search_info_var.set(f"Found 0 instances of [{query}]")
        else:
            self.search_index = 0
            self.search_info_var.set(f"Found {n} instances of [{query}]")
            self._scroll_to_match()

    def _on_search_next(self):
        if not self.search_matches:
            return
        self.search_index = (self.search_index + 1) % len(self.search_matches)
        self._scroll_to_match()

    def _on_search_prev(self):
        if not self.search_matches:
            return
        self.search_index = (self.search_index - 1) % len(self.search_matches)
        self._scroll_to_match()

    def _scroll_to_match(self):
        if not self.search_matches:
            return
        idx = self.search_matches[self.search_index]
        iid = str(idx)
        self.tree.selection_set(iid)
        self.tree.see(iid)
        pos = self.search_index + 1
        total = len(self.search_matches)
        query = self.search_var.get().strip()
        self.search_info_var.set(
            f"Found {total} instances of [{query}]  ({pos}/{total})"
        )

    # ── Coverage (Stage 4) ─────────────────────────────────────────

    def _on_coverage(self):
        if not self.trace_rows:
            messagebox.showwarning("No Data",
                                   "Run Analyze first to load a trace.")
            return
        if not self.codebase_dir:
            # Prompt user to pick codebase dir now
            path = filedialog.askdirectory(
                title="Select Codebase Directory for Coverage"
            )
            if not path:
                return
            self.codebase_dir = path
            self.codebase_dir_var.set(path)

        CoverageWindow(self.root, self.codebase_dir, self.trace_rows)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ProfilerTraceApp()
