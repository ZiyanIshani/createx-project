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
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlparse

# Allow running from the due_diligence directory directly
sys.path.insert(0, os.path.dirname(__file__))

from repo_ingestion.file_tree import language_breakdown
from repo_ingestion.git_stats import (
    bus_factor_data,
    commit_velocity,
    commits_per_email,
    contributor_recency_score,
    contributor_timeline,
    lines_per_contributor,
)
from static_analysis.dep_graph import (
    architectural_risk_score,
    build_dep_graph,
    compute_metrics,
)
from static_analysis.graph_viz import render_contributor_file_graph
from static_analysis.test_coverage import compute_test_coverage


def _looks_like_git_url(value: str) -> bool:
    """Best-effort check for common git URL formats."""
    if value.startswith(("http://", "https://", "git@")):
        return True
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc)


def _clone_repo_to_temp(repo_url: str) -> str:
    """
    Clone `repo_url` into a temporary directory and return the local path.
    Raises RuntimeError on clone failure.
    """
    temp_root = tempfile.mkdtemp(prefix="due-diligence-")
    dest = os.path.join(temp_root, "repo")
    cmd = ["git", "clone", "--depth", "1", repo_url, dest]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        shutil.rmtree(temp_root, ignore_errors=True)
        raise RuntimeError(stderr or f"Failed to clone repository: {repo_url}")
    return dest


def _run_pipeline(repo_path: str, ref: str = "HEAD", use_llm: bool = False) -> dict:
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
    single_contributor_files = {
        path: emails
        for path, emails in bus_data.items()
        if len(emails) == 1
    }
    bus_factor_risk = [
        {"file": path, "sole_contributor": emails[0]}
        for path, emails in list(single_contributor_files.items())[:10]
    ]

    velocity = commit_velocity(repo_path, ref=ref)
    timeline = contributor_timeline(repo_path, ref=ref)

    # --- Generate contributor ↔ file graph image ---
    images_dir = os.path.join(os.path.abspath(repo_path), "images")
    graph_image_path = render_contributor_file_graph(bus_data, images_dir)

    # --- Step 2: Static Analysis ---
    graph = build_dep_graph(repo_path)
    metrics = compute_metrics(graph)
    arch_risk = architectural_risk_score(metrics)

    # --- Step 3: Test Coverage ---
    test_cov = compute_test_coverage(repo_path, dep_graph=graph)

    # --- Step 4: LLM Summaries (optional) ---
    llm_summaries: list = []
    if use_llm:
        try:
            from llm_summaries import summarize_repo
            llm_result = summarize_repo(
                repo_path, model="gpt-5-mini", top_k=5, min_in_degree=1,
            )
            llm_summaries = llm_result.get("summaries", [])
        except Exception as exc:
            print(f"Warning: LLM summaries failed: {exc}", file=sys.stderr)

    return {
        "repo_path": os.path.abspath(repo_path),
        "languages": languages,
        "contributors": top_contributors,
        "bus_factor_risk": bus_factor_risk,
        "commit_velocity": velocity,
        "contributor_timeline": timeline,
        "bus_data": bus_data,
        "dep_graph_metrics": metrics,
        "architectural_risk": arch_risk,
        "test_coverage": test_cov,
        "llm_summaries": llm_summaries,
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

    # Commit velocity
    vel = result.get("commit_velocity", {})
    if vel.get("total_commits"):
        print("COMMIT VELOCITY")
        print(sep)
        print(f"  Total commits:    {vel['total_commits']}")
        print(f"  First commit:     {vel['first_commit_date']}")
        print(f"  Last commit:      {vel['last_commit_date']}")
        months = vel.get("months", [])
        cpm = vel.get("commits_per_month", [])
        if months:
            avg = sum(cpm) / len(cpm)
            print(f"  Months spanned:   {len(months)}")
            print(f"  Avg commits/mo:   {avg:.1f}")
            recent = cpm[-3:] if len(cpm) >= 3 else cpm
            print(f"  Last {len(recent)} months:     {recent}")
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

    # Test coverage
    tc = result.get("test_coverage", {})
    if tc:
        print("TEST COVERAGE")
        print(sep)
        print(f"  Test files:         {tc.get('test_file_count', 0)}")
        print(f"  Source files:       {tc.get('source_file_count', 0)}")
        print(f"  Test:source ratio:  {tc.get('test_to_source_ratio', 0):.2f}")
        print(f"  Coverage estimate:  {tc.get('coverage_percent', 0):.1f}%")
        untested = tc.get("untested_files", [])
        if untested:
            print(f"\n  Untested modules ({len(untested)} shown):")
            for f in untested[:10]:
                print(f"    {f}")
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

    # LLM summaries
    llm = result.get("llm_summaries", [])
    if llm:
        print("LLM FILE SUMMARIES")
        print(sep)
        for s in llm:
            print(f"\n  {s.get('file', '?')}")
            print(f"  Role: {s.get('role', 'N/A')}")
            risks = s.get("risk_notes", [])
            if risks:
                for r in risks:
                    print(f"    ⚠ {r}")
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
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Generate LLM summaries for high-centrality files (requires OPENAI_API_KEY).",
    )
    args = parser.parse_args()

    # Accept both local paths and remote git URLs in repo_path.
    pipeline_repo_path = args.repo_path
    cleanup_root: str | None = None
    if _looks_like_git_url(args.repo_path):
        try:
            pipeline_repo_path = _clone_repo_to_temp(args.repo_path)
            cleanup_root = os.path.dirname(pipeline_repo_path)
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
    elif not os.path.isdir(args.repo_path):
        print(f"Error: '{args.repo_path}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    try:
        result = _run_pipeline(pipeline_repo_path, ref=args.ref, use_llm=args.llm)
    finally:
        if cleanup_root is not None:
            shutil.rmtree(cleanup_root, ignore_errors=True)

    if args.output == "pretty":
        _print_pretty(result)
    else:
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
