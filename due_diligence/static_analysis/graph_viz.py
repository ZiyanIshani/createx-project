"""
graph_viz.py — generate a visual contributor-file graph as a PNG image.

Produces a bipartite-style graph where:
  - Person nodes (contributors) are coloured blue
  - File nodes are coloured orange
  - Edges connect a person to every file they have touched (via git blame)
"""

from __future__ import annotations

import os
from typing import Dict, List

import matplotlib

matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt
import networkx as nx


def _short_label(path: str, max_len: int = 25) -> str:
    """Shorten a file path for display."""
    if len(path) <= max_len:
        return path
    return "..." + path[-(max_len - 3) :]


def _short_name(email: str) -> str:
    """Extract a display name from an email address."""
    return email.split("@")[0]


def build_contributor_file_graph(
    bus_data: Dict[str, List[str]],
) -> nx.Graph:
    """
    Build an undirected bipartite graph from bus_factor_data output.

    Nodes carry a "kind" attribute: "person" or "file".
    """
    g = nx.Graph()

    for file_path, emails in bus_data.items():
        g.add_node(file_path, kind="file")
        for email in emails:
            g.add_node(email, kind="person")
            g.add_edge(email, file_path)

    return g


def render_contributor_file_graph(
    bus_data: Dict[str, List[str]],
    output_dir: str,
    filename: str = "contributor_file_graph.png",
) -> str:
    """
    Render the contributor ↔ file graph to a PNG image.

    Returns the absolute path to the saved image.
    """
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, filename)

    g = build_contributor_file_graph(bus_data)

    if g.number_of_nodes() == 0:
        # Nothing to draw — create a placeholder image
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, "No contributor data available",
                ha="center", va="center", fontsize=14)
        ax.set_axis_off()
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return output_path

    person_nodes = [n for n, d in g.nodes(data=True) if d["kind"] == "person"]
    file_nodes = [n for n, d in g.nodes(data=True) if d["kind"] == "file"]

    # Layout: spring layout works well for bipartite-ish graphs
    pos = nx.spring_layout(g, k=1.8, iterations=50, seed=42)

    # Scale figure to graph size, clamped to reasonable bounds
    node_count = g.number_of_nodes()
    fig_size = max(10, min(24, node_count * 0.4))
    fig, ax = plt.subplots(figsize=(fig_size, fig_size * 0.7))

    # Draw edges
    nx.draw_networkx_edges(g, pos, ax=ax, alpha=0.3, edge_color="#999999", width=0.8)

    # Draw person nodes
    nx.draw_networkx_nodes(
        g, pos, nodelist=person_nodes, ax=ax,
        node_color="#4A90D9", node_size=400, alpha=0.9,
    )

    # Draw file nodes
    nx.draw_networkx_nodes(
        g, pos, nodelist=file_nodes, ax=ax,
        node_color="#E8913A", node_size=200, node_shape="s", alpha=0.9,
    )

    # Labels
    person_labels = {n: _short_name(n) for n in person_nodes}
    file_labels = {n: _short_label(n) for n in file_nodes}

    nx.draw_networkx_labels(
        g, pos, labels=person_labels, ax=ax,
        font_size=9, font_weight="bold", font_color="#1a1a1a",
    )
    nx.draw_networkx_labels(
        g, pos, labels=file_labels, ax=ax,
        font_size=6, font_color="#333333",
    )

    # Legend
    ax.scatter([], [], c="#4A90D9", s=100, label="Contributor")
    ax.scatter([], [], c="#E8913A", s=80, marker="s", label="File")
    ax.legend(loc="upper left", fontsize=10, framealpha=0.8)

    ax.set_title("Contributor ↔ File Ownership Graph", fontsize=14, pad=12)
    ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    return output_path
