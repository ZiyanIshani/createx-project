#!/usr/bin/env python3
"""
main.py — CLI entrypoint for the AI-powered due diligence pipeline.

Usage:
    python main.py <repo_path> [--ref HEAD] [--output json|pretty]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Allow running from the due_diligence directory directly
sys.path.insert(0, os.path.dirname(__file__))

from repo_ingestion.file_tree import language_breakdown
from repo_ingestion.git_stats import (
    bus_factor_data,
    commits_per_email,
    contributor_recency_score,
    lines_per_contributor,
)
from static_analysis.dep_graph import (
    architectural_risk_score,
    build_dep_graph,
    compute_metrics,
)
from static_analysis.graph_viz import render_contributor_file_graph


def _run_pipeline(repo_path: str, ref: str = "HEAD") -> dict:
    # --- Step 1: Repository Ingestion ---
    languages = language_breakdown(repo_path)

    raw_contributors = commits_per_email(repo_path, ref=ref)
    augmented = contributor_recency_score(raw_contributors, repo_path=repo_path, ref=ref)
    lines_by_email = lines_per_contributor(repo_path, ref=ref)

    top_contributors = [
        {
            "commit_count": count,
            "name": name,
            "email": email,
            "last_commit_ts": last_ts,
            "recency_score": recency,
            "lines_added": lines_by_email.get(email, 0),
        }
        for count, name, email, last_ts, recency in augmented[:10]
    ]

    bus_data = bus_factor_data(repo_path, ref=ref)
    # Files with only one unique contributor = highest bus factor risk
    single_contributor_files = {
        path: emails
        for path, emails in bus_data.items()
        if len(emails) == 1
    }
    # Sort by contributor recency (proxy: sort descending by email alphabetically if no ts)
    bus_factor_risk = [
        {"file": path, "sole_contributor": emails[0]}
        for path, emails in list(single_contributor_files.items())[:10]
    ]

    # --- Generate contributor ↔ file graph image ---
    images_dir = os.path.join(os.path.abspath(repo_path), "images")
    graph_image_path = render_contributor_file_graph(bus_data, images_dir)

    # --- Step 2: Static Analysis ---
    graph = build_dep_graph(repo_path)
    metrics = compute_metrics(graph)
    arch_risk = architectural_risk_score(metrics)

    return {
        "repo_path": os.path.abspath(repo_path),
        "languages": languages,
        "contributors": top_contributors,
        "bus_factor_risk": bus_factor_risk,
        "bus_data": bus_data,
        "dep_graph_metrics": metrics,
        "architectural_risk": arch_risk,
        "contributor_file_graph": graph_image_path,
    }


def _print_pretty(result: dict) -> None:
    sep = "-" * 60

    print(f"\n{'=' * 60}")
    print(f"  DUE DILIGENCE REPORT")
    print(f"  Repository: {result['repo_path']}")
    print(f"{'=' * 60}\n")

    # Languages
    print("LANGUAGE BREAKDOWN")
    print(sep)
    summary = result["languages"].get("summary", {})
    for lang, count in sorted(summary.items(), key=lambda x: x[1], reverse=True):
        print(f"  {lang:<20} {count} file(s)")
    print()

    # Contributors
    print("TOP CONTRIBUTORS")
    print(sep)
    for c in result["contributors"]:
        recency_label = {1.0: "active", 0.5: "semi-active", 0.0: "inactive"}.get(
            c["recency_score"], "unknown"
        )
        print(
            f"  {c['name']:<25} {c['commit_count']:>5} commits  "
            f"[{recency_label}]  {c['email']}"
        )
    print()

    # Bus factor risk
    print("BUS FACTOR RISK (files with single contributor)")
    print(sep)
    if result["bus_factor_risk"]:
        for item in result["bus_factor_risk"]:
            print(f"  {item['file']:<40} sole: {item['sole_contributor']}")
    else:
        print("  None detected.")
    print()

    # Dependency graph metrics
    m = result["dep_graph_metrics"]
    print("DEPENDENCY GRAPH METRICS")
    print(sep)
    print(f"  Internal files:        {m['internal_file_count']}")
    print(f"  External dependencies: {m['external_dep_count']}")
    print(f"  Edges:                 {m['edge_count']}")
    print(f"  Avg in-degree:         {m['avg_in_degree']:.2f}")
    print(f"  Max in-degree:         {m['max_in_degree']}")
    print(f"  Orphaned files:        {len(m['orphaned_files'])}")
    print(f"  Circular dep groups:   {len(m['circular_dependency_groups'])}")

    if m["fragile_files"]:
        print("\n  Most-imported files (fragile hubs):")
        for ff in m["fragile_files"]:
            print(f"    {ff['file']:<40} in-degree: {ff['in_degree']}")

    if m["top_external_deps"]:
        print("\n  Top external dependencies:")
        for dep in m["top_external_deps"][:5]:
            print(f"    {dep['package']:<30} imports: {dep['import_count']}")

    print()

    # Architectural risk
    ar = result["architectural_risk"]
    print("ARCHITECTURAL RISK SCORE")
    print(sep)
    print(f"  Score: {ar['score']}/10")
    print("  Reasons:")
    for reason in ar["reasons"]:
        print(f"    • {reason}")
    print()

    # Graph image
    if result.get("contributor_file_graph"):
        print("CONTRIBUTOR ↔ FILE GRAPH")
        print(sep)
        print(f"  Saved to: {result['contributor_file_graph']}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI-powered technical due diligence pipeline."
    )
    parser.add_argument("repo_path", help="Path to the git repository to analyse.")
    parser.add_argument("--ref", default="HEAD", help="Git ref to analyse (default: HEAD).")
    parser.add_argument(
        "--output",
        choices=["json", "pretty"],
        default="json",
        help="Output format (default: json).",
    )
    args = parser.parse_args()

    if not os.path.isdir(args.repo_path):
        print(f"Error: '{args.repo_path}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    result = _run_pipeline(args.repo_path, ref=args.ref)

    if args.output == "pretty":
        _print_pretty(result)
    else:
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
