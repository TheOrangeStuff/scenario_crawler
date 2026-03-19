"""Build and display a directed call graph from a call sequence.

Constructs a networkx DiGraph of caller->callee relationships weighted by
call count, and renders it on a matplotlib Axes.
"""

from typing import Optional

import matplotlib.pyplot as plt
import networkx as nx

from .parse_profiler_phases import CallEvent


def build_call_graph(
    ax: plt.Axes,
    call_sequence: list[CallEvent],
    *,
    highlight_name: str = "",
    layout: str = "dot",
    max_nodes: int = 100,
) -> tuple[nx.DiGraph, Optional[dict]]:
    """Build and plot a directed call graph.

    Args:
        ax: Matplotlib axes to draw on.
        call_sequence: List of CallEvent from parse_profiler_phases.
        highlight_name: Function name substring to highlight in red.
        layout: Graph layout algorithm — 'dot', 'spring', 'circular',
                'kamada_kawai', or 'shell'.
        max_nodes: Maximum number of nodes to display.

    Returns:
        Tuple of (DiGraph, position dict or None).
    """
    ax.clear()

    if not call_sequence:
        ax.set_title("No data to display")
        return nx.DiGraph(), None

    # Build edge counts from caller-callee relationships using a stack
    call_stack: list[str] = []
    edge_counts: dict[tuple[str, str], int] = {}

    for entry in call_sequence:
        if entry.event == "enter":
            if call_stack:
                caller = call_stack[-1]
                callee = entry.func_name
                edge_key = (caller, callee)
                edge_counts[edge_key] = edge_counts.get(edge_key, 0) + 1
            call_stack.append(entry.func_name)
        elif entry.event == "exit" and call_stack:
            # Pop matching name from top of stack
            for s in range(len(call_stack) - 1, -1, -1):
                if call_stack[s] == entry.func_name:
                    call_stack.pop(s)
                    break

    if not edge_counts:
        ax.set_title("No call relationships found")
        return nx.DiGraph(), None

    # Build the graph
    G = nx.DiGraph()
    for (src, tgt), weight in edge_counts.items():
        G.add_edge(src, tgt, weight=weight)

    # Prune to max_nodes by total edge weight
    if G.number_of_nodes() > max_nodes:
        node_weights = {}
        for node in G.nodes():
            w = sum(d["weight"] for _, _, d in G.in_edges(node, data=True))
            w += sum(d["weight"] for _, _, d in G.out_edges(node, data=True))
            node_weights[node] = w
        sorted_nodes = sorted(node_weights, key=node_weights.get, reverse=True)
        keep = set(sorted_nodes[:max_nodes])
        remove = [n for n in G.nodes() if n not in keep]
        G.remove_nodes_from(remove)

    # Compute layout
    try:
        if layout == "dot":
            # Try graphviz if available, fall back to spring
            try:
                pos = nx.drawing.nx_agraph.graphviz_layout(G, prog="dot")
            except (ImportError, Exception):
                pos = nx.spring_layout(G, k=2.0, iterations=50, seed=42)
        elif layout == "spring":
            pos = nx.spring_layout(G, k=2.0, iterations=50, seed=42)
        elif layout == "circular":
            pos = nx.circular_layout(G)
        elif layout == "kamada_kawai":
            pos = nx.kamada_kawai_layout(G)
        elif layout == "shell":
            pos = nx.shell_layout(G)
        else:
            pos = nx.spring_layout(G, k=2.0, iterations=50, seed=42)
    except Exception:
        pos = nx.spring_layout(G, k=2.0, iterations=50, seed=42)

    # Draw
    weights = [G[u][v]["weight"] for u, v in G.edges()]
    max_weight = max(weights) if weights else 1

    # Node colors
    highlight_lower = highlight_name.lower() if highlight_name else ""
    node_colors = []
    node_sizes = []
    for node in G.nodes():
        if highlight_lower and highlight_lower in node.lower():
            node_colors.append("red")
            node_sizes.append(600)
        else:
            node_colors.append("#3388cc")
            node_sizes.append(300)

    # Edge widths scaled by weight
    edge_widths = [0.5 + 3.5 * (w / max_weight) for w in weights]

    nx.draw_networkx_nodes(
        G, pos, ax=ax,
        node_color=node_colors, node_size=node_sizes, alpha=0.9,
    )
    nx.draw_networkx_labels(
        G, pos, ax=ax,
        font_size=7, font_weight="bold",
    )
    nx.draw_networkx_edges(
        G, pos, ax=ax,
        width=edge_widths, alpha=0.6,
        arrows=True, arrowsize=12,
        connectionstyle="arc3,rad=0.1",
    )

    # Edge labels (weights)
    edge_labels = {(u, v): str(d["weight"]) for u, v, d in G.edges(data=True)}
    nx.draw_networkx_edge_labels(
        G, pos, ax=ax,
        edge_labels=edge_labels, font_size=6, alpha=0.7,
    )

    ax.set_title(f"Call Graph ({G.number_of_nodes()} nodes, {G.number_of_edges()} edges)")
    ax.set_axis_off()

    return G, pos
