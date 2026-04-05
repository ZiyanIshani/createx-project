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
    commit_velocity,
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
from static_analysis.test_coverage import compute_test_coverage


def _run_pipeline(
    repo_path: str,
    ref: str = "HEAD",
    use_llm: bool = False,
    standards_path: str | None = None,
    model: str = "mistral",
    ollama_url: str = "http://localhost:11434",
) -> dict:
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

    # --- Generate contributor ↔ file graph image ---
    images_dir = os.path.join(os.path.abspath(repo_path), "images")
    graph_image_path = render_contributor_file_graph(bus_data, images_dir)

    # --- Step 2: Static Analysis ---
    graph = build_dep_graph(repo_path)
    metrics = compute_metrics(graph)
    arch_risk = architectural_risk_score(metrics)

    # --- Step 3: Test Coverage ---
    test_cov = compute_test_coverage(repo_path, dep_graph=graph)

    # --- Step 4: LLM Agentic Analysis (optional) ---
    llm_summaries: list = []
    llm_analysis: dict = {}

    if use_llm:
        from llm.client import OllamaClient, OllamaConnectionError
        from llm.agents.authorship import AuthorshipAgent
        from llm.agents.provenance import ProvenanceAgent
        from llm.agents.quality import QualityAgent

        client = OllamaClient(base_url=ollama_url, model=model)

        if not client.is_available():
            print(
                f"Warning: Ollama not available at {ollama_url}. Skipping LLM analysis.",
                file=sys.stderr,
            )
            llm_analysis = {"error": f"Ollama not available at {ollama_url}"}
        else:
            # Identify critical files: union of fragile + single-contributor, cap at 10
            fragile_files = metrics.get("fragile_files", [])
            fragile_paths = {e["file"] for e in fragile_files}
            single_contrib_paths = set(single_contributor_files.keys())
            critical_paths = list(fragile_paths | single_contrib_paths)[:10]

            # Build per-file language map from languages summary
            per_file_languages: dict[str, str] = {}
            try:
                from repo_ingestion.file_tree import walk_repo
                for fpath, lang in walk_repo(repo_path):
                    rel = os.path.relpath(fpath, repo_path)
                    per_file_languages[rel] = lang
            except Exception:
                pass

            # Build contributor recency map
            contributor_recency_map = {
                c["email"]: c["recency_score"] for c in top_contributors
            }

            # Authorship
            auth_agent = AuthorshipAgent(client)
            authorship_results = auth_agent.analyze_critical_files(
                metrics, bus_data, contributor_recency_map, top_n=5
            )

            # Provenance
            prov_agent = ProvenanceAgent(client)
            provenance_results = prov_agent.scan_files(
                critical_paths, repo_path, per_file_languages
            )

            # Quality
            quality_agent = QualityAgent(client)
            critical_fragile = [e for e in fragile_files if e["file"] in set(critical_paths)]
            quality_results = quality_agent.analyze_critical_files(
                critical_fragile, repo_path, per_file_languages, standards_path
            )

            llm_analysis = {
                "model": model,
                "authorship": authorship_results,
                "provenance": provenance_results,
                "quality": quality_results,
            }

    return {
        "repo_path": os.path.abspath(repo_path),
        "languages": languages,
        "contributors": top_contributors,
        "bus_factor_risk": bus_factor_risk,
        "commit_velocity": velocity,
        "bus_data": bus_data,
        "dep_graph_metrics": metrics,
        "architectural_risk": arch_risk,
        "test_coverage": test_cov,
        "llm_summaries": llm_summaries,
        "llm_analysis": llm_analysis,
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

    # LLM Agentic Analysis
    llm_a = result.get("llm_analysis", {})
    if llm_a and "error" not in llm_a:
        print(f"LLM ANALYSIS  (model: {llm_a.get('model', 'unknown')})")
        print(sep)

        authorship = llm_a.get("authorship", [])
        if authorship:
            print("\n  AUTHORSHIP RISK")
            for entry in authorship:
                print(
                    f"    [{entry.get('risk_level', '?').upper():8s}] "
                    f"{entry.get('file', '?'):<40} "
                    f"{entry.get('risk_summary', '')[:80]}"
                )

        provenance = llm_a.get("provenance", [])
        if provenance:
            print("\n  PROVENANCE RISK")
            for entry in provenance:
                ev_count = len(entry.get("evidence", []))
                print(
                    f"    [{entry.get('provenance_risk', '?').upper():6s}] "
                    f"{entry.get('file', '?'):<40} "
                    f"{ev_count} evidence item(s)"
                )

        quality = llm_a.get("quality", [])
        if quality:
            print("\n  CODE QUALITY")
            for entry in quality:
                print(
                    f"    [Grade {entry.get('overall_grade', '?')}] "
                    f"{entry.get('file', '?'):<40} "
                    f"{entry.get('violation_count', 0)} violation(s)"
                )
        print()
    elif llm_a.get("error"):
        print("LLM ANALYSIS")
        print(sep)
        print(f"  {llm_a['error']}")
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
        help="Enable LLM agentic analysis via Ollama (off by default).",
    )
    parser.add_argument(
        "--standards",
        default=None,
        metavar="PATH",
        help="Path to a coding standards file (markdown or text).",
    )
    parser.add_argument(
        "--model",
        default="mistral",
        help="Ollama model name (default: mistral).",
    )
    parser.add_argument(
        "--ollama-url",
        default="http://localhost:11434",
        help="Ollama base URL (default: http://localhost:11434).",
    )
    args = parser.parse_args()

    if not os.path.isdir(args.repo_path):
        print(f"Error: '{args.repo_path}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    result = _run_pipeline(
        args.repo_path,
        ref=args.ref,
        use_llm=args.llm,
        standards_path=args.standards,
        model=args.model,
        ollama_url=args.ollama_url,
    )

    if args.output == "pretty":
        _print_pretty(result)
    else:
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
