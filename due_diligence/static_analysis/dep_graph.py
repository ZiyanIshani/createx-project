"""
dep_graph.py — dependency graph construction and risk metrics using NetworkX.
"""

from __future__ import annotations

import os
import posixpath
from collections import defaultdict
from typing import Dict, List, Optional

import networkx as nx

from repo_ingestion.file_tree import language_breakdown
from static_analysis.ast_parser import parse_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _module_stem(path: str) -> str:
    """Return the module name stem for a file path (no extension, no leading /)."""
    base = posixpath.basename(path)
    stem, _ = posixpath.splitext(base)
    return stem


def _path_without_ext(path: str) -> str:
    root, _ = posixpath.splitext(path)
    return root


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_import(
    raw_import: str,
    source_file: str,
    all_files: List[str],
    language: str,
) -> Optional[str]:
    """
    Resolve a raw import string to a repo-relative path or "external:X".

    Returns:
        resolved relative path string  — if found in the repo
        "external:<raw_import>"        — if not found locally
        None                           — if resolution is meaningless (e.g. empty)
    """
    if not raw_import:
        return None

    raw_import = raw_import.strip()

    # Relative import: starts with . or ..
    if raw_import.startswith("."):
        # Resolve relative to source_file directory
        source_dir = posixpath.dirname(source_file)
        resolved = posixpath.normpath(posixpath.join(source_dir, raw_import))

        # Try exact match first
        if resolved in all_files:
            return resolved

        # Try with common extensions
        for ext in [".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".c", ".h"]:
            candidate = resolved + ext
            if candidate in all_files:
                return candidate

        # Try as directory with __init__ / index
        for index in ["__init__.py", "index.js", "index.ts", "mod.rs"]:
            candidate = posixpath.join(resolved, index)
            if candidate in all_files:
                return candidate

        return None

    # Absolute/package import — try to find a matching file in the repo
    # Build lookup structures once per call (small repos, acceptable perf)
    all_files_set = set(all_files)

    # Try exact path match (e.g. "utils/helpers")
    if raw_import in all_files_set:
        return raw_import

    # Try matching by module stem (last component without extension)
    module_stem = raw_import.split(".")[-1] if "." in raw_import else raw_import
    # Also handle slashes (Go-style "github.com/foo/bar" → "bar")
    module_stem = module_stem.split("/")[-1]

    for f in all_files:
        if _module_stem(f) == module_stem:
            return f

    # Try path-without-ext match for dotted names → path conversion
    # e.g. "utils.helpers" → "utils/helpers.py"
    path_guess = raw_import.replace(".", "/")
    for ext in [".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".c", ".h"]:
        candidate = path_guess + ext
        if candidate in all_files_set:
            return candidate

    # Not found locally — external
    # Strip version specifiers / URL fragments for cleaner labelling
    pkg_name = raw_import.split("/")[0].split(".")[0]
    return f"external:{pkg_name}"


def build_dep_graph(repo_path: str) -> nx.DiGraph:
    """
    Build and return a NetworkX DiGraph of the repo's dependency graph.

    Nodes: file paths (relative) and "external:<pkg>" strings.
    Edges: A → B means A imports B.
    """
    breakdown = language_breakdown(repo_path)
    per_file: Dict[str, str] = breakdown.get("per_file", {})
    all_files: List[str] = list(per_file.keys())

    graph = nx.DiGraph()

    # Add all internal files as nodes first
    for f in all_files:
        graph.add_node(f)

    for file_path, language in per_file.items():
        abs_path = os.path.join(repo_path, file_path)
        result = parse_file(abs_path, language)
        imports = result.get("imports", [])

        for raw_import in imports:
            resolved = resolve_import(raw_import, file_path, all_files, language)
            if resolved is None:
                continue
            if resolved not in graph:
                graph.add_node(resolved)
            graph.add_edge(file_path, resolved)

    return graph


def compute_metrics(graph: nx.DiGraph) -> Dict[str, object]:
    """
    Compute structural metrics from the dependency graph.
    """
    all_nodes = list(graph.nodes())
    internal_nodes = [n for n in all_nodes if not n.startswith("external:")]
    external_nodes = [n for n in all_nodes if n.startswith("external:")]

    node_count = len(all_nodes)
    edge_count = graph.number_of_edges()
    external_dep_count = len(external_nodes)
    internal_file_count = len(internal_nodes)

    # in-degree stats (internal files only)
    internal_in_degrees = [(n, graph.in_degree(n)) for n in internal_nodes]
    internal_in_degrees.sort(key=lambda x: x[1], reverse=True)

    fragile_files = [
        {"file": n, "in_degree": d}
        for n, d in internal_in_degrees[:5]
        if d > 0
    ]

    avg_in_degree = (
        sum(d for _, d in internal_in_degrees) / internal_file_count
        if internal_file_count > 0
        else 0.0
    )
    max_in_degree = max((d for _, d in internal_in_degrees), default=0)

    # Circular dependency groups: SCCs with size > 1 (internal nodes only)
    # Build subgraph of internal nodes only
    internal_subgraph = graph.subgraph(internal_nodes)
    sccs = [
        sorted(scc)
        for scc in nx.strongly_connected_components(internal_subgraph)
        if len(scc) > 1
    ]

    # Orphaned files: internal nodes with no internal connections.
    # A file is orphaned only if nothing imports it AND it imports no other
    # internal file.  Files that only import external packages (e.g. all Go
    # files in a single-package repo, or C files that only #include stdlib
    # headers) are NOT orphaned — they're actively used code; they just don't
    # cross-reference each other inside the repo.
    internal_nodes_set = set(internal_nodes)
    orphaned_files = [
        n for n in internal_nodes
        if graph.in_degree(n) == 0
        and not any(dest in internal_nodes_set for dest in graph.successors(n))
    ]

    # Top external deps by import count (in-degree in the full graph)
    external_counts = [
        {"package": n.replace("external:", ""), "import_count": graph.in_degree(n)}
        for n in external_nodes
    ]
    external_counts.sort(key=lambda x: x["import_count"], reverse=True)
    top_external_deps = external_counts[:10]

    return {
        "node_count": node_count,
        "edge_count": edge_count,
        "external_dep_count": external_dep_count,
        "internal_file_count": internal_file_count,
        "fragile_files": fragile_files,
        "circular_dependency_groups": sccs,
        "orphaned_files": orphaned_files,
        "avg_in_degree": round(avg_in_degree, 3),
        "max_in_degree": max_in_degree,
        "top_external_deps": top_external_deps,
    }


def architectural_risk_score(metrics: Dict[str, object]) -> Dict[str, object]:
    """
    Compute a 0–10 risk score from computed metrics.
    Returns {"score": int, "reasons": [str]}.
    """
    score = 0
    reasons: List[str] = []

    node_count: int = metrics.get("internal_file_count", 0)  # type: ignore
    sccs: List = metrics.get("circular_dependency_groups", [])  # type: ignore
    max_in: int = metrics.get("max_in_degree", 0)  # type: ignore
    orphaned: List = metrics.get("orphaned_files", [])  # type: ignore

    # --- Circular dependencies ---
    scc_count = len(sccs)
    if scc_count == 1:
        score += 2
        reasons.append(f"1 circular dependency group detected.")
    elif scc_count == 2:
        score += 3
        reasons.append(f"{scc_count} circular dependency groups detected.")
    elif scc_count > 2:
        score += min(4, scc_count)
        reasons.append(f"{scc_count} circular dependency groups detected (high coupling risk).")

    # --- High in-degree (god files / fragile hubs) ---
    if node_count > 0:
        ratio = max_in / node_count
        if ratio > 0.5:
            score += 3
            reasons.append(
                f"Max in-degree ({max_in}) is {ratio:.0%} of internal file count — likely a fragile hub."
            )
        elif ratio > 0.25:
            score += 2
            reasons.append(
                f"Max in-degree ({max_in}) is {ratio:.0%} of internal file count — moderate hub concentration."
            )
        elif ratio > 0.1:
            score += 1
            reasons.append(
                f"Max in-degree ({max_in}) is {ratio:.0%} of internal file count."
            )

    # --- Orphaned files ---
    if node_count > 0:
        orphan_ratio = len(orphaned) / node_count
        if orphan_ratio > 0.5:
            score += 3
            reasons.append(
                f"{len(orphaned)} orphaned files ({orphan_ratio:.0%} of codebase) — likely dead code or broken imports."
            )
        elif orphan_ratio > 0.25:
            score += 2
            reasons.append(
                f"{len(orphaned)} orphaned files ({orphan_ratio:.0%} of codebase)."
            )
        elif orphan_ratio > 0.1:
            score += 1
            reasons.append(
                f"{len(orphaned)} orphaned files ({orphan_ratio:.0%} of codebase)."
            )

    score = min(score, 10)

    if not reasons:
        reasons.append("No significant architectural risk factors detected.")

    return {"score": score, "reasons": reasons}
