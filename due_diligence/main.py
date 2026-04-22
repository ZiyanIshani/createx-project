#!/usr/bin/env python3
"""
main.py — CLI entrypoint for the AI-powered due diligence pipeline.

Usage:
    python main.py <repo_path> [--ref HEAD] [--output json|pretty]
"""

from __future__ import annotations

import argparse
import json
import math
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


def _compute_code_churn(repo_path: str) -> dict:
    """
    Identify 'hot' files — those with disproportionately high commit frequency
    relative to the rest of the codebase.

    A file is flagged as a hot spot when its commit count exceeds 2× the
    median file commit count (with a floor of 3 commits to suppress noise on
    brand-new or rarely-touched files).  Using the median as the baseline means
    the signal is self-calibrating: it adapts to the repo's own activity level
    rather than requiring a hand-tuned absolute threshold, so a small quiet repo
    (gron, 223 commits) and a large active one (10,000 commits) are judged by
    the same relative standard.

    High churn on a specific file signals instability — the code is hard to get
    right, likely poorly factored, or a bottleneck that many changes flow through.
    All of these are direct contributors to technical debt.
    """
    import statistics
    from repo_ingestion.file_tree import discover_files

    _skip_exts = {
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
        ".woff", ".woff2", ".ttf", ".eot",
        ".pdf", ".zip", ".tar", ".gz",
        ".lock", ".sum", ".mod", ".min.js",
    }

    _empty: dict = {
        "hot_file_count": 0, "hot_file_ratio": 0.0,
        "total_files": 0, "median_commits": 0.0, "hot_files": [],
    }

    all_files = discover_files(repo_path)
    source_files = [
        f for f in all_files
        if os.path.splitext(f)[1].lower() not in _skip_exts
    ]
    if not source_files:
        return _empty

    # --- Per-file commit counts (one subprocess per file, unambiguous) ---
    file_counts: dict[str, int] = {}
    for rel_path in source_files:
        try:
            count_str = subprocess.check_output(
                ["git", "rev-list", "--count", "HEAD", "--", rel_path],
                cwd=repo_path, text=True, stderr=subprocess.DEVNULL,
            ).strip()
            file_counts[rel_path] = int(count_str) if count_str.isdigit() else 0
        except Exception:
            file_counts[rel_path] = 0

    counts = list(file_counts.values())
    median_count = statistics.median(counts) if counts else 0.0

    # Hot threshold: 2× the median, but never lower than 3 commits
    hot_cutoff = max(median_count * 2.0, 3)

    hot_files = [
        {
            "file":    path,
            "commits": count,
            "vs_median": round(count / max(median_count, 1), 1),
        }
        for path, count in sorted(file_counts.items(), key=lambda x: -x[1])
        if count >= hot_cutoff
    ]

    return {
        "hot_file_count":  len(hot_files),
        "hot_file_ratio":  len(hot_files) / len(source_files),
        "total_files":     len(source_files),
        "median_commits":  round(median_count, 1),
        "hot_files":       hot_files[:10],
    }


def _compute_doc_density(repo_path: str, per_file_languages: dict) -> float:
    """
    Return the fraction of non-blank code lines that are comments or docstrings.

    Supports Python, Go, JavaScript, TypeScript, Rust, Java, C/C++.
    Returns a value in [0, 1]; higher = more documentation.
    """
    _comment_prefixes: dict[str, tuple[str, ...]] = {
        "Python":     ("#", '"""', "'''"),
        "Go":         ("//",),
        "JavaScript": ("//", "/*", " *"),
        "TypeScript": ("//", "/*", " *"),
        "Rust":       ("//",),
        "Java":       ("//", "/*", " *"),
        "C":          ("//", "/*", " *"),
        "C++":        ("//", "/*", " *"),
    }

    total_lines = 0
    doc_lines = 0

    for rel_path, lang in per_file_languages.items():
        prefixes = _comment_prefixes.get(lang)
        if not prefixes:
            continue
        abs_path = os.path.join(repo_path, rel_path)
        try:
            with open(abs_path, "r", errors="ignore") as fh:
                for line in fh:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    total_lines += 1
                    if any(stripped.startswith(p) for p in prefixes):
                        doc_lines += 1
        except OSError:
            continue

    return doc_lines / total_lines if total_lines > 0 else 0.0


def _remediation_estimate(debt_score: int, total_files: int) -> str:
    """
    Deterministic remediation time estimate based on debt score and codebase size.

    Model assumptions:
    - 2 engineers devoting 20% of sprint capacity to debt reduction
      = 2 × 20 working days × 0.20 = 8 engineer-days available per month
    - Score scales non-linearly (^1.5): low debt is cheap, high debt compounds
    - Codebase size scales on a log curve relative to a 50-file reference repo
    - Expressed as a ±25% range to be honest about estimation uncertainty

    Calibration reference points (50-file repo):
      score 20  →  ~0.5 months   ("2-4 weeks")
      score 40  →  ~1.5 months   ("1-2 months")
      score 60  →  ~3 months     ("2-4 months")
      score 80  →  ~5.5 months   ("4-7 months")
      score 100 →  ~7.5 months   ("6-10 months")
    """
    if debt_score <= 3:
        return "< 1 week"

    # 8 engineer-days of debt-reduction capacity per month
    eng_days_per_month = 8.0

    # Base days for a reference 50-file codebase at score=100
    base_days = 60.0

    # Non-linear score factor: debt compounds at higher scores
    score_factor = (debt_score / 100.0) ** 1.5

    # Log-scale size factor relative to a 50-file reference repo
    size_factor = max(0.4, math.log10(total_files + 1) / math.log10(51))

    raw_days = base_days * score_factor * size_factor
    months = raw_days / eng_days_per_month

    low = max(0.1, months * 0.75)
    high = months * 1.25

    if high < 0.35:
        return "< 1 week"
    if high < 0.6:
        return "1-2 weeks"
    if high < 1.0:
        return "2-4 weeks"
    if low < 1.0:
        return f"1-{math.ceil(high)} months"
    return f"{math.floor(low)}-{math.ceil(high)} months"


def _compute_debt_scores(
    metrics: dict,
    test_coverage: dict,
    bus_factor_risk: list,
    churn_data: dict | None = None,
    doc_density: float = 0.0,
    top_contributors: list | None = None,
) -> dict:
    """
    Return component scores (0-100 each, higher = more debt) and a weighted total.

    Weights (sum to 1.0):
      knowledge concentration  25%  — bus factor + contributor dominance
      test coverage gaps       25%  — missing tests = fragile changes
      code churn               20%  — hot files = unstable, hard-to-maintain code
      orphaned / dead code     15%  — unused files add maintenance burden
      hub fragility            10%  — heavily-imported files are risky to change
      documentation density     5%  — low docs = high onboarding / knowledge cost
    """
    top_contributors = top_contributors or []
    churn_data = churn_data or {}
    total_files = max(metrics.get("internal_file_count", 1), 1)
    coverage_pct = test_coverage.get("coverage_percent", 0)

    # --- Knowledge concentration (bus factor + contributor dominance) ---
    file_bus_score = min(int((len(bus_factor_risk) / total_files) * 100 * 2.5), 100)
    total_commits = sum(c["commit_count"] for c in top_contributors) or 1
    top_share = top_contributors[0]["commit_count"] / total_commits if top_contributors else 0
    dominance_score = min(int(max(top_share - 0.5, 0) * 200), 100)
    bus_score = min(int(file_bus_score * 0.5 + dominance_score * 0.5), 100)

    # --- Test coverage gaps ---
    test_score = min(int(100 - coverage_pct), 100)

    # --- Code churn (hot files) ---
    # hot_file_ratio = fraction of source files that are >2× the median commit count.
    # Scale: 0% hot → 0, ≥33% hot → 100.
    hot_ratio = churn_data.get("hot_file_ratio", 0.0)
    churn_score = min(int(hot_ratio * 300), 100)

    # --- Hub fragility ---
    max_in_deg = metrics.get("max_in_degree", 0)
    hub_score = min(int((max_in_deg / (total_files * 0.15 + 1)) * 100), 100)

    # --- Documentation density ---
    # Target 15% doc density as "acceptable"; below that scales to 100.
    # doc_density=0 → score 100; doc_density≥0.15 → score 0
    doc_score = min(int(max(0.15 - doc_density, 0) / 0.15 * 100), 100)

    total = int(
        bus_score   * 0.30 +
        test_score  * 0.25 +
        churn_score * 0.25 +
        hub_score   * 0.15 +
        doc_score   * 0.05
    )

    top_name = top_contributors[0]["name"] if top_contributors else "unknown"
    remediation = _remediation_estimate(total, total_files)

    return {
        "bus_score":            bus_score,
        "test_score":           test_score,
        "churn_score":          churn_score,
        "hub_score":            hub_score,
        "doc_score":            doc_score,
        "total":                total,
        "remediation_estimate": remediation,
        # Raw inputs for the LLM narrative
        "bf_file_count":         len(bus_factor_risk),
        "coverage_pct":          coverage_pct,
        "coverage_estimated":    test_coverage.get("coverage_estimated", False),
        "hot_file_count":        churn_data.get("hot_file_count", 0),
        "hot_file_ratio_pct":    round(hot_ratio * 100, 1),
        "median_commits":        churn_data.get("median_commits", 0.0),
        "doc_density_pct":       round(doc_density * 100, 1),
        "max_in_degree":         max_in_deg,
        "total_files":           total_files,
        "top_contributor_share": round(top_share * 100, 1),
        "top_contributor_name":  top_name,
    }


def _run_pipeline(
    repo_path: str,
    ref: str = "HEAD",
    use_llm: bool = False,
    standards_path: str | None = None,
    model: str = "llama-3.1-8b-instant",
    top_n: int = 3,
) -> dict:
    # --- Step 1: Repository Ingestion ---
    languages = language_breakdown(repo_path)

    raw_contributors = commits_per_email(repo_path, ref=ref)
    augmented = contributor_recency_score(raw_contributors, repo_path=repo_path, ref=ref)
    lines_by_email = lines_per_contributor(repo_path, ref=ref)

    # Merge entries that share the same display name (e.g. same person with
    # two Git identities / a noreply GitHub address and a real one).
    _merged: dict[str, dict] = {}
    for count, name, email, last_ts, recency in augmented:
        key = name.strip().lower()
        lines = lines_by_email.get(email, 0)
        if key not in _merged:
            _merged[key] = {
                "name": name,
                "commit_count": count,
                "emails": [email],
                "last_commit_ts": last_ts,
                "recency_score": recency,
                "lines_added": lines,
            }
        else:
            entry = _merged[key]
            entry["commit_count"] += count
            entry["lines_added"] += lines
            entry["emails"].append(email)
            if last_ts > entry["last_commit_ts"]:
                entry["last_commit_ts"] = last_ts
            if recency > entry["recency_score"]:
                entry["recency_score"] = recency

    top_contributors = sorted(
        _merged.values(), key=lambda x: x["commit_count"], reverse=True
    )[:10]

    # Resolve a single primary email per contributor: prefer a real address
    # over a GitHub noreply address so the table reads cleanly.
    for c in top_contributors:
        real = [e for e in c["emails"] if "noreply" not in e]
        c["email"] = real[0] if real else c["emails"][0]

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

    # --- Step 3b: Per-file language map (used by subscriptions, doc density, LLM) ---
    # language_breakdown() was already called at the top of the pipeline; reuse it.
    per_file_languages: dict[str, str] = languages.get("per_file", {})

    # --- Step 3c: Code churn + documentation density for debt scoring ---
    churn_data = _compute_code_churn(repo_path)
    doc_density = _compute_doc_density(repo_path, per_file_languages)

    # --- Debt scores (always computed so the template can use them) ---
    debt_scores = _compute_debt_scores(
        metrics, test_cov, bus_factor_risk,
        churn_data=churn_data,
        doc_density=doc_density,
        top_contributors=top_contributors,
    )

    # --- Subscription Service Detection (heuristic, always runs) ---
    _per_file_languages_sub = per_file_languages

    from llm.agents.subscriptions import SubscriptionDetector
    _sub_detector = SubscriptionDetector()
    _sub_matches = _sub_detector.scan(repo_path, _per_file_languages_sub)
    subscription_services = _sub_detector.summarize(_sub_matches)

    # --- Step 4: LLM Agentic Analysis (optional, Groq-based) ---
    llm_analysis: dict = {}

    if use_llm:
        try:
            from llm.client import GroqClient, GroqConnectionError
            from llm.agents.authorship import AuthorshipAgent
            from llm.agents.provenance import ProvenanceAgent
            from llm.agents.quality import QualityAgent

            client = GroqClient(model=model)

            if not client.is_available():
                print("Warning: Groq API not available. Skipping LLM analysis.", file=sys.stderr)
                llm_analysis = {"error": "Groq API not available — set GROQ_API_KEY and try again."}
            else:
                # Build per-file language map
                per_file_languages: dict[str, str] = {}
                try:
                    from repo_ingestion.file_tree import walk_repo
                    for fpath, lang in walk_repo(repo_path):
                        rel = os.path.relpath(fpath, repo_path)
                        per_file_languages[rel] = lang
                except Exception:
                    pass

                contributor_recency_map = {
                    email: c["recency_score"]
                    for c in top_contributors
                    for email in c["emails"]
                }

                # Pick critical files: union of fragile + single-contributor, cap at top_n
                fragile_files = metrics.get("fragile_files", [])
                fragile_paths = {e["file"] for e in fragile_files}
                critical_paths = list(fragile_paths | set(single_contributor_files.keys()))[:top_n]

                auth_agent = AuthorshipAgent(client)
                authorship_results = auth_agent.analyze_critical_files(
                    metrics, bus_data, contributor_recency_map, top_n=top_n
                )

                prov_agent = ProvenanceAgent(client)
                provenance_results = prov_agent.scan_files(
                    critical_paths, repo_path, per_file_languages
                )

                critical_fragile = [e for e in fragile_files if e["file"] in set(critical_paths)]
                quality_agent = QualityAgent(client)
                quality_results = quality_agent.analyze_critical_files(
                    critical_fragile, repo_path, per_file_languages, standards_path
                )

                # Debt narrative — plain paragraph; estimate is now computed deterministically
                debt_narrative = ""
                try:
                    ds = debt_scores
                    label = "high" if ds["total"] >= 60 else ("moderate" if ds["total"] >= 30 else "low")
                    debt_prompt = (
                        f"Technical debt score: {ds['total']}/100 ({label})\n\n"
                        f"Component breakdown:\n"
                        f"  - Knowledge concentration: {ds['bus_score']}/100 "
                        f"({ds['top_contributor_name']} holds {ds['top_contributor_share']}% of all commits; "
                        f"{ds['bf_file_count']} of {ds['total_files']} files have a single contributor)\n"
                        f"  - Test coverage gaps: {ds['test_score']}/100 "
                        f"({'estimated' if ds.get('coverage_estimated') else 'measured'} coverage: {ds['coverage_pct']:.1f}%)\n"
                        f"  - Code churn: {ds['churn_score']}/100 "
                        f"({ds['hot_file_count']} of {ds['total_files']} files are hot spots — "
                        f"touched more than 2× the median file ({ds['median_commits']} commits); "
                        f"{ds['hot_file_ratio_pct']}% of source files are disproportionately unstable)\n"
                        f"  - Hub fragility: {ds['hub_score']}/100 "
                        f"(max in-degree: {ds['max_in_degree']})\n"
                        f"  - Documentation density: {ds['doc_score']}/100 "
                        f"({ds['doc_density_pct']}% of code lines are comments/docstrings)\n\n"
                        f"Write a single plain-English paragraph (3-5 sentences) explaining what is "
                        f"driving this score and what it means for future engineering effort. "
                        f"Name specific contributors or files where relevant. Do not include a time estimate — "
                        f"that is provided separately. Do not use bullet points or markdown."
                    )
                    narrative_resp = client.chat([
                        {"role": "system", "content": (
                            "You are a senior technical due diligence analyst writing for an M&A report. "
                            "Be direct, precise, and jargon-free. Output only the paragraph — no headings, no markdown."
                        )},
                        {"role": "user", "content": debt_prompt},
                    ], max_tokens=300)
                    debt_narrative = narrative_resp["choices"][0]["message"]["content"].strip()
                except Exception as e:
                    print(f"Warning: Groq debt narrative failed: {e}", file=sys.stderr)

                llm_analysis = {
                    "model": model,
                    "authorship": authorship_results,
                    "provenance": provenance_results,
                    "quality": quality_results,
                    "debt_narrative": debt_narrative,
                }
        except Exception as exc:
            print(f"Warning: Groq LLM analysis failed: {exc}", file=sys.stderr)
            llm_analysis = {"error": str(exc)}

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
        "subscription_services": {
            "service_count": subscription_services["service_count"],
            "services": subscription_services["services"],
            "by_category": subscription_services["by_category"],
        },
        "debt_scores": debt_scores,
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

    # Subscription Services
    sub = result.get("subscription_services", {})
    if sub and sub.get("service_count", 0) > 0:
        print("SUBSCRIPTION SERVICES DETECTED")
        print(sep)
        total_files = sum(s["reference_count"] for s in sub.get("services", []))
        print(f"  {sub['service_count']} external service(s) found\n")
        by_cat = sub.get("by_category", {})
        services_by_name = {s["service"]: s for s in sub.get("services", [])}
        for category, svc_names in sorted(by_cat.items()):
            print(f"  {category}")
            for svc_name in svc_names:
                s = services_by_name.get(svc_name, {})
                print(
                    f"    {svc_name:<20} {s.get('tier', ''):<20} "
                    f"{s.get('reference_count', 0):>3} reference(s)"
                )
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
        help="Enable LLM analysis via Groq API (free tier: 30 RPM, 14400 RPD).",
    )
    parser.add_argument(
        "--standards",
        default=None,
        metavar="PATH",
        help="Path to a coding standards file (markdown or text).",
    )
    parser.add_argument(
        "--model",
        default="llama-3.1-8b-instant",
        help="Groq model name (default: llama-3.1-8b-instant).",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=3,
        help="Number of critical files to run LLM analysis on (default: 3).",
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
        top_n=args.top_n,
    )

    if args.output == "pretty":
        _print_pretty(result)
    else:
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
