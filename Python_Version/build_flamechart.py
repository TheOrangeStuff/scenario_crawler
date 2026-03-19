"""Build a flamechart visualization from a call sequence.

Draws stacked rectangles on a matplotlib Axes where x = sequence position
and y = call depth. Supports highlighting by function name and click callbacks.
"""

from dataclasses import dataclass, field
from typing import Optional, Callable

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.colors as mcolors
import numpy as np

from .parse_profiler_phases import CallEvent


@dataclass
class FlamechartRect:
    """Metadata for one rectangle in the flamechart."""
    x: float
    width: float
    depth: int
    func_name: str
    file_name: str
    seq_index: int
    patch: Optional[mpatches.FancyBboxPatch] = None
    text: Optional[plt.Text] = None


def build_flamechart(
    ax: plt.Axes,
    call_sequence: list[CallEvent],
    *,
    highlight_name: str = "",
    colormap: Optional[np.ndarray] = None,
    on_click: Optional[Callable[[FlamechartRect], None]] = None,
) -> list[FlamechartRect]:
    """Render a flamechart on the given axes.

    Args:
        ax: Matplotlib axes to draw on.
        call_sequence: List of CallEvent from parse_profiler_phases.
        highlight_name: Function name substring to highlight in red.
        colormap: Nx3 array of RGB colors (0-1). Defaults to tab20.
        on_click: Callback invoked when a rectangle is clicked.

    Returns:
        List of FlamechartRect with references to the drawn patches.
    """
    ax.clear()

    if not call_sequence:
        ax.set_title("No data to display")
        return []

    if colormap is None:
        cmap = plt.cm.tab20
        colormap = np.array([cmap(i / 20) [:3] for i in range(20)])

    # Pair enter/exit events using a stack to build rectangles
    @dataclass
    class _StackEntry:
        x_start: int
        depth: int
        seq_index: int
        func_name: str
        file_name: str

    stack: list[_StackEntry] = []
    rects: list[FlamechartRect] = []
    enter_count = 0
    max_depth = 0

    for entry in call_sequence:
        if entry.event == "enter":
            enter_count += 1
            stack.append(_StackEntry(
                x_start=enter_count,
                depth=entry.depth,
                seq_index=entry.index,
                func_name=entry.func_name,
                file_name=entry.file_name,
            ))
            max_depth = max(max_depth, entry.depth)
        elif entry.event == "exit" and stack:
            # Pop the topmost matching entry
            pop_idx = len(stack) - 1
            for s in range(len(stack) - 1, -1, -1):
                if stack[s].func_name == entry.func_name:
                    pop_idx = s
                    break
            info = stack.pop(pop_idx)
            rects.append(FlamechartRect(
                x=info.x_start,
                width=enter_count - info.x_start + 1,
                depth=info.depth,
                func_name=info.func_name,
                file_name=info.file_name,
                seq_index=info.seq_index,
            ))

    # Flush remaining stack entries (unmatched enters)
    for info in stack:
        rects.append(FlamechartRect(
            x=info.x_start,
            width=enter_count - info.x_start + 1,
            depth=info.depth,
            func_name=info.func_name,
            file_name=info.file_name,
            seq_index=info.seq_index,
        ))

    if not rects:
        ax.set_title("No rectangles to draw")
        return []

    # Assign colors by function name
    unique_names = sorted(set(r.func_name for r in rects))
    n_colors = len(colormap)
    color_map = {
        name: colormap[i % n_colors] for i, name in enumerate(unique_names)
    }

    bar_height = 0.85
    highlight_lower = highlight_name.lower() if highlight_name else ""

    for r in rects:
        x_pos = r.x - 0.5
        y_pos = r.depth - 1
        w = r.width
        h = bar_height

        face_color = color_map[r.func_name]

        if highlight_lower and highlight_lower in r.func_name.lower():
            edge_color = "red"
            line_width = 2.5
        else:
            edge_color = (0.3, 0.3, 0.3)
            line_width = 0.5

        patch = mpatches.FancyBboxPatch(
            (x_pos, y_pos), w, h,
            boxstyle="round,pad=0.02",
            facecolor=face_color,
            edgecolor=edge_color,
            linewidth=line_width,
        )
        ax.add_patch(patch)
        r.patch = patch

        # Add text label if rectangle is wide enough
        if w > 2:
            txt = ax.text(
                x_pos + w / 2, y_pos + h / 2, r.func_name,
                ha="center", va="center", fontsize=6,
                clip_on=True,
            )
            r.text = txt

    # Set up click handler
    if on_click:
        def _on_pick(event):
            for r in rects:
                if r.patch is not None and r.patch.contains(event)[0]:
                    on_click(r)
                    break

        ax.figure.canvas.mpl_connect("button_press_event", _on_pick)

    ax.set_xlim(0, enter_count + 1)
    ax.set_ylim(-0.5, max_depth + 1)
    ax.invert_yaxis()
    ax.set_xlabel("Call Sequence Position")
    ax.set_ylabel("Call Depth")
    ax.set_title("Flamechart")

    return rects


def highlight_rects_by_name(
    rects: list[FlamechartRect], func_name: str
) -> None:
    """Highlight all rectangles matching func_name, dim the rest."""
    for r in rects:
        if r.patch is None:
            continue
        if r.func_name.lower() == func_name.lower():
            r.patch.set_edgecolor("red")
            r.patch.set_linewidth(2.5)
        else:
            r.patch.set_edgecolor((0.3, 0.3, 0.3))
            r.patch.set_linewidth(0.5)
