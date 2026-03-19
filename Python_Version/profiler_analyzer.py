"""Interactive MATLAB profiler analysis GUI built with Tkinter + matplotlib.

Launch with:
    python -m Python_Version                    # file picker
    python -m Python_Version path/to/data.mat   # direct load
"""

import re
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from .parse_profiler_phases import parse_profiler_phases, PhaseParseResult, CallEvent
from .build_flamechart import build_flamechart, highlight_rects_by_name, FlamechartRect
from .build_call_graph import build_call_graph
from .scan_codebase_coverage import scan_codebase_coverage, CoverageResult


class ProfilerAnalyzer:
    """Main application class."""

    def __init__(self, mat_file: Optional[str] = None):
        self.mat_file: Optional[str] = None
        self.codebase_dir: Optional[str] = None
        self.parse_result: Optional[PhaseParseResult] = None
        self.filtered_sequence: list[CallEvent] = []
        self.flamechart_rects: list[FlamechartRect] = []
        self.coverage_result: Optional[CoverageResult] = None
        self.exclude_list: list[str] = []
        self.search_matches: list[int] = []
        self.search_index: int = 0

        self._build_ui()

        if mat_file:
            self.mat_file = mat_file
            self._load_data()

        self.root.mainloop()

    # ── UI Construction ──────────────────────────────────────────────

    def _build_ui(self):
        self.root = tk.Tk()
        self.root.title("Profiler Analyzer")
        self.root.geometry("1400x850")
        self.root.minsize(900, 600)

        # Top bar
        top_frame = ttk.Frame(self.root, padding=4)
        top_frame.pack(fill=tk.X)

        ttk.Button(top_frame, text="Load .mat", command=self._on_load_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="Codebase Dir", command=self._on_select_codebase).pack(side=tk.LEFT, padx=2)

        ttk.Separator(top_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Label(top_frame, text="Start Phase:").pack(side=tk.LEFT, padx=(4, 0))
        self.start_phase_var = tk.IntVar(value=1)
        self.start_phase_spin = ttk.Spinbox(top_frame, from_=1, to=9999, width=5,
                                             textvariable=self.start_phase_var)
        self.start_phase_spin.pack(side=tk.LEFT, padx=2)

        ttk.Label(top_frame, text="End Phase:").pack(side=tk.LEFT, padx=(4, 0))
        self.end_phase_var = tk.IntVar(value=1)
        self.end_phase_spin = ttk.Spinbox(top_frame, from_=1, to=9999, width=5,
                                           textvariable=self.end_phase_var)
        self.end_phase_spin.pack(side=tk.LEFT, padx=2)

        ttk.Button(top_frame, text="Analyze", command=self._on_analyze).pack(side=tk.LEFT, padx=4)

        self.info_label_var = tk.StringVar(value="No data loaded")
        ttk.Label(top_frame, textvariable=self.info_label_var).pack(side=tk.LEFT, padx=8)

        # Filter bar
        filter_frame = ttk.Frame(self.root, padding=4)
        filter_frame.pack(fill=tk.X)

        self.hide_builtins_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(filter_frame, text="Hide Builtins",
                        variable=self.hide_builtins_var).pack(side=tk.LEFT, padx=2)

        self.hide_matlabroot_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(filter_frame, text="Hide matlabroot",
                        variable=self.hide_matlabroot_var).pack(side=tk.LEFT, padx=2)

        ttk.Separator(filter_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Button(filter_frame, text="+Excl", width=5,
                   command=self._on_add_exclusion).pack(side=tk.LEFT, padx=2)

        self.exclude_combo_var = tk.StringVar(value="(none)")
        self.exclude_combo = ttk.Combobox(filter_frame, textvariable=self.exclude_combo_var,
                                           values=["(none)"], state="readonly", width=18)
        self.exclude_combo.pack(side=tk.LEFT, padx=2)

        ttk.Button(filter_frame, text="-Excl", width=5,
                   command=self._on_remove_exclusion).pack(side=tk.LEFT, padx=2)

        ttk.Separator(filter_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(filter_frame, textvariable=self.search_var, width=22)
        search_entry.pack(side=tk.LEFT, padx=2)
        search_entry.bind("<Return>", lambda _: self._on_search())

        ttk.Button(filter_frame, text="Search", command=self._on_search).pack(side=tk.LEFT, padx=2)
        ttk.Button(filter_frame, text="< Prev", command=self._on_search_prev).pack(side=tk.LEFT, padx=1)
        ttk.Button(filter_frame, text="Next >", command=self._on_search_next).pack(side=tk.LEFT, padx=1)

        self.search_match_var = tk.StringVar(value="")
        ttk.Label(filter_frame, textvariable=self.search_match_var).pack(side=tk.LEFT, padx=4)

        # Main content: PanedWindow (left = table, right = notebook with tabs)
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # ── Left: call sequence table ──
        left_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=1)

        columns = ("seq", "event", "function", "file", "type", "depth")
        self.tree = ttk.Treeview(left_frame, columns=columns, show="headings",
                                  selectmode="browse")
        self.tree.heading("seq", text="Seq")
        self.tree.heading("event", text="Event")
        self.tree.heading("function", text="Function")
        self.tree.heading("file", text="File")
        self.tree.heading("type", text="Type")
        self.tree.heading("depth", text="Depth")

        self.tree.column("seq", width=45, anchor="center")
        self.tree.column("event", width=50, anchor="center")
        self.tree.column("function", width=200)
        self.tree.column("file", width=180)
        self.tree.column("type", width=70)
        self.tree.column("depth", width=45, anchor="center")

        tree_scroll_y = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.tree.yview)
        tree_scroll_x = ttk.Scrollbar(left_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=tree_scroll_y.set,
                            xscrollcommand=tree_scroll_x.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll_y.grid(row=0, column=1, sticky="ns")
        tree_scroll_x.grid(row=1, column=0, sticky="ew")
        left_frame.rowconfigure(0, weight=1)
        left_frame.columnconfigure(0, weight=1)

        self.tree.bind("<<TreeviewSelect>>", self._on_table_select)
        self.tree.bind("<Double-1>", self._on_table_double_click)

        # Enable column sorting
        for col in columns:
            self.tree.heading(col, command=lambda c=col: self._sort_column(c, False))

        # ── Right: notebook with tabs ──
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=1)

        self.notebook = ttk.Notebook(right_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Flamechart tab
        flame_frame = ttk.Frame(self.notebook)
        self.notebook.add(flame_frame, text="Flamechart")

        self.flame_fig, self.flame_ax = plt.subplots(figsize=(6, 4))
        self.flame_fig.tight_layout()
        self.flame_canvas = FigureCanvasTkAgg(self.flame_fig, master=flame_frame)
        self.flame_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        flame_toolbar = NavigationToolbar2Tk(self.flame_canvas, flame_frame)
        flame_toolbar.update()

        # Call Graph tab
        graph_frame = ttk.Frame(self.notebook)
        self.notebook.add(graph_frame, text="Call Graph")

        graph_control = ttk.Frame(graph_frame, padding=2)
        graph_control.pack(fill=tk.X)
        ttk.Label(graph_control, text="Layout:").pack(side=tk.LEFT, padx=2)
        self.graph_layout_var = tk.StringVar(value="spring")
        graph_layout_combo = ttk.Combobox(graph_control,
                                           textvariable=self.graph_layout_var,
                                           values=["dot", "spring", "circular",
                                                    "kamada_kawai", "shell"],
                                           state="readonly", width=14)
        graph_layout_combo.pack(side=tk.LEFT, padx=2)
        ttk.Button(graph_control, text="Refresh", command=self._refresh_call_graph).pack(side=tk.LEFT, padx=2)

        self.graph_fig, self.graph_ax = plt.subplots(figsize=(6, 4))
        self.graph_fig.tight_layout()
        self.graph_canvas = FigureCanvasTkAgg(self.graph_fig, master=graph_frame)
        self.graph_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        graph_toolbar = NavigationToolbar2Tk(self.graph_canvas, graph_frame)
        graph_toolbar.update()

        # Coverage tab
        cov_frame = ttk.Frame(self.notebook)
        self.notebook.add(cov_frame, text="Coverage")

        cov_top = ttk.Frame(cov_frame, padding=2)
        cov_top.pack(fill=tk.X)

        self.cov_pct_var = tk.StringVar(value="No codebase loaded")
        ttk.Label(cov_top, textvariable=self.cov_pct_var,
                  font=("TkDefaultFont", 12, "bold")).pack(side=tk.LEFT, padx=4)

        self.cov_uncalled_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(cov_top, text="Show uncalled only",
                        variable=self.cov_uncalled_only_var,
                        command=self._refresh_coverage_table).pack(side=tk.LEFT, padx=8)

        # Coverage bar chart
        self.cov_fig, self.cov_ax = plt.subplots(figsize=(6, 1.2))
        self.cov_fig.tight_layout()
        self.cov_canvas = FigureCanvasTkAgg(self.cov_fig, master=cov_frame)
        self.cov_canvas.get_tk_widget().pack(fill=tk.X, padx=4, pady=2)

        # Coverage table
        cov_columns = ("name", "file", "called", "count")
        self.cov_tree = ttk.Treeview(cov_frame, columns=cov_columns, show="headings",
                                      selectmode="browse")
        self.cov_tree.heading("name", text="Function")
        self.cov_tree.heading("file", text="File")
        self.cov_tree.heading("called", text="Called")
        self.cov_tree.heading("count", text="Count")

        self.cov_tree.column("name", width=150)
        self.cov_tree.column("file", width=250)
        self.cov_tree.column("called", width=60, anchor="center")
        self.cov_tree.column("count", width=60, anchor="center")

        cov_scroll = ttk.Scrollbar(cov_frame, orient=tk.VERTICAL, command=self.cov_tree.yview)
        self.cov_tree.configure(yscrollcommand=cov_scroll.set)
        self.cov_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0), pady=2)
        cov_scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 4), pady=2)

        self.cov_tree.bind("<Double-1>", self._on_coverage_double_click)

    # ── Data Loading ─────────────────────────────────────────────────

    def _on_load_file(self):
        path = filedialog.askopenfilename(
            title="Select Profiler .mat File",
            filetypes=[("MAT files", "*.mat"), ("All files", "*.*")],
        )
        if not path:
            return
        self.mat_file = path
        self._load_data()

    def _load_data(self):
        try:
            result = parse_profiler_phases(self.mat_file, 1, 1)
            self.parse_result = result
            self.info_label_var.set(f"Loaded: {result.total_phases} phases detected")
            self.end_phase_var.set(min(result.total_phases, 1))
        except Exception as e:
            messagebox.showerror("Load Error", str(e))

    def _on_analyze(self):
        if not self.mat_file:
            messagebox.showerror("Error", "No .mat file loaded.")
            return

        start_p = self.start_phase_var.get()
        end_p = self.end_phase_var.get()

        try:
            self.parse_result = parse_profiler_phases(
                self.mat_file, start_p, end_p,
                hide_builtins=self.hide_builtins_var.get(),
                hide_matlabroot=self.hide_matlabroot_var.get(),
                exclude_names=self.exclude_list,
            )
            self.filtered_sequence = self.parse_result.call_sequence

            n_events = len(self.filtered_sequence)
            total = self.parse_result.total_phases
            self.info_label_var.set(
                f"Phases {start_p}-{end_p} | {n_events} events | {total} total phases"
            )

            self._update_table()
            self._refresh_flamechart()
            self._refresh_call_graph()

            if self.codebase_dir:
                self._refresh_coverage()

        except Exception as e:
            messagebox.showerror("Analysis Error", str(e))

    # ── Filtering ────────────────────────────────────────────────────

    def _on_add_exclusion(self):
        name = simpledialog.askstring("Add Exclusion", "Function name to exclude:")
        if not name or not name.strip():
            return
        name = name.strip()
        if name.lower() not in {n.lower() for n in self.exclude_list}:
            self.exclude_list.append(name)
        self._update_exclude_combo()

    def _on_remove_exclusion(self):
        selected = self.exclude_combo_var.get()
        if selected == "(none)" or not self.exclude_list:
            return
        self.exclude_list = [n for n in self.exclude_list if n.lower() != selected.lower()]
        self._update_exclude_combo()

    def _update_exclude_combo(self):
        if self.exclude_list:
            self.exclude_combo["values"] = self.exclude_list
            self.exclude_combo_var.set(self.exclude_list[0])
        else:
            self.exclude_combo["values"] = ["(none)"]
            self.exclude_combo_var.set("(none)")

    # ── Table ────────────────────────────────────────────────────────

    def _update_table(self):
        self.tree.delete(*self.tree.get_children())
        for ev in self.filtered_sequence:
            self.tree.insert("", tk.END, iid=str(ev.index), values=(
                ev.index, ev.event, ev.func_name, ev.file_name, ev.func_type, ev.depth,
            ))

    def _sort_column(self, col: str, reverse: bool):
        items = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]
        try:
            items.sort(key=lambda t: int(t[0]), reverse=reverse)
        except ValueError:
            items.sort(key=lambda t: t[0].lower(), reverse=reverse)
        for idx, (_, k) in enumerate(items):
            self.tree.move(k, "", idx)
        self.tree.heading(col, command=lambda: self._sort_column(col, not reverse))

    def _on_table_select(self, _event):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        idx = int(iid) - 1
        if 0 <= idx < len(self.filtered_sequence):
            func_name = self.filtered_sequence[idx].func_name
            self._highlight_flamechart(func_name)

    def _on_table_double_click(self, _event):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        idx = int(iid) - 1
        if 0 <= idx < len(self.filtered_sequence):
            file_name = self.filtered_sequence[idx].file_name
            if file_name and Path(file_name).is_file():
                self._open_file(file_name)

    # ── Search ───────────────────────────────────────────────────────

    def _on_search(self):
        query = self.search_var.get().strip()
        if not query or not self.filtered_sequence:
            self.search_matches = []
            self.search_index = 0
            self.search_match_var.set("")
            return

        self.search_matches = [
            i for i, ev in enumerate(self.filtered_sequence)
            if re.search(query, ev.func_name, re.IGNORECASE)
        ]
        if not self.search_matches:
            self.search_index = 0
            self.search_match_var.set("0 matches")
        else:
            self.search_index = 0
            self.search_match_var.set(f"1 of {len(self.search_matches)}")
            self._scroll_to_match()

    def _on_search_next(self):
        if not self.search_matches:
            return
        self.search_index = (self.search_index + 1) % len(self.search_matches)
        self.search_match_var.set(f"{self.search_index + 1} of {len(self.search_matches)}")
        self._scroll_to_match()

    def _on_search_prev(self):
        if not self.search_matches:
            return
        self.search_index = (self.search_index - 1) % len(self.search_matches)
        self.search_match_var.set(f"{self.search_index + 1} of {len(self.search_matches)}")
        self._scroll_to_match()

    def _scroll_to_match(self):
        if not self.search_matches:
            return
        idx = self.search_matches[self.search_index]
        ev = self.filtered_sequence[idx]
        iid = str(ev.index)
        self.tree.selection_set(iid)
        self.tree.see(iid)
        self._highlight_flamechart(ev.func_name)

    # ── Flamechart ───────────────────────────────────────────────────

    def _refresh_flamechart(self):
        if not self.filtered_sequence:
            self.flame_ax.clear()
            self.flame_ax.set_title("No data")
            self.flame_canvas.draw()
            return

        highlight = self.search_var.get().strip()
        self.flamechart_rects = build_flamechart(
            self.flame_ax, self.filtered_sequence,
            highlight_name=highlight,
            on_click=self._on_flamechart_click,
        )
        self.flame_canvas.draw()

    def _on_flamechart_click(self, rect: FlamechartRect):
        self.info_label_var.set(f"Selected: {rect.func_name}")
        self._highlight_table_by_name(rect.func_name)

    def _highlight_flamechart(self, func_name: str):
        if self.flamechart_rects:
            highlight_rects_by_name(self.flamechart_rects, func_name)
            self.flame_canvas.draw()

    def _highlight_table_by_name(self, func_name: str):
        for ev in self.filtered_sequence:
            if ev.func_name.lower() == func_name.lower():
                iid = str(ev.index)
                self.tree.selection_set(iid)
                self.tree.see(iid)
                return

    # ── Call Graph ───────────────────────────────────────────────────

    def _refresh_call_graph(self):
        if not self.filtered_sequence:
            self.graph_ax.clear()
            self.graph_ax.set_title("No data")
            self.graph_canvas.draw()
            return

        highlight = self.search_var.get().strip()
        build_call_graph(
            self.graph_ax, self.filtered_sequence,
            highlight_name=highlight,
            layout=self.graph_layout_var.get(),
        )
        self.graph_canvas.draw()

    # ── Coverage ─────────────────────────────────────────────────────

    def _on_select_codebase(self):
        path = filedialog.askdirectory(title="Select Codebase Root Directory")
        if not path:
            return
        self.codebase_dir = path
        if self.parse_result:
            self._refresh_coverage()

    def _refresh_coverage(self):
        if not self.codebase_dir or not self.parse_result:
            return

        try:
            self.coverage_result = scan_codebase_coverage(
                self.codebase_dir,
                self.filtered_sequence,
                self.parse_result.function_table,
            )

            n_called = len(self.coverage_result.called_functions)
            n_total = len(self.coverage_result.codebase_functions)
            self.cov_pct_var.set(
                f"Coverage: {self.coverage_result.coverage_percent:.1f}% "
                f"({n_called} / {n_total} functions)"
            )

            self._draw_coverage_bar()
            self._refresh_coverage_table()

        except Exception as e:
            messagebox.showerror("Coverage Error", str(e))

    def _draw_coverage_bar(self):
        ax = self.cov_ax
        ax.clear()

        if not self.coverage_result:
            self.cov_canvas.draw()
            return

        n_called = len(self.coverage_result.called_functions)
        n_uncalled = len(self.coverage_result.uncalled_functions)
        n_total = n_called + n_uncalled

        if n_total == 0:
            self.cov_canvas.draw()
            return

        ax.barh(0, n_total, height=0.5, color="#cc3333", label="Uncalled")
        ax.barh(0, n_called, height=0.5, color="#33aa55", label="Called")
        ax.set_xlim(0, n_total)
        ax.set_yticks([])
        ax.set_xlabel("Functions")
        ax.legend(loc="upper right", fontsize=8)
        self.cov_fig.tight_layout()
        self.cov_canvas.draw()

    def _refresh_coverage_table(self):
        self.cov_tree.delete(*self.cov_tree.get_children())
        if not self.coverage_result:
            return

        entries = self.coverage_result.entries
        if self.cov_uncalled_only_var.get():
            entries = [e for e in entries if not e.called]

        for e in entries:
            self.cov_tree.insert("", tk.END, values=(
                e.name, e.file, "Yes" if e.called else "No", e.call_count,
            ))

    def _on_coverage_double_click(self, _event):
        sel = self.cov_tree.selection()
        if not sel:
            return
        values = self.cov_tree.item(sel[0], "values")
        if values and len(values) >= 2:
            file_path = values[1]
            if file_path and Path(file_path).is_file():
                self._open_file(file_path)

    # ── Utility ──────────────────────────────────────────────────────

    @staticmethod
    def _open_file(file_path: str):
        """Open a file in the system default editor."""
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", file_path])
            elif sys.platform == "win32":
                subprocess.Popen(["start", "", file_path], shell=True)
            else:
                subprocess.Popen(["xdg-open", file_path])
        except Exception:
            pass
