#!/usr/bin/env python3
"""
llm_high_innode_summaries.py

Generate LLM summaries for the highest in-degree INTERNAL files in a repo's
dependency graph, excluding external-library nodes.

Usage:
    python llm_high_innode_summaries.py <repo_path> [--top-k 10] [--min-in-degree 1]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

from openai import OpenAI

sys.path.insert(0, os.path.dirname(__file__))

from repo_ingestion.file_tree import language_breakdown
from static_analysis.dep_graph import build_dep_graph


MAX_FILE_CHARS = 12000
DEFAULT_MODEL = "gpt-5-mini"

def read_file_safely(path: str, max_chars: int = MAX_FILE_CHARS) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return ""

    if len(text) <= max_chars:
        return text

    head = text[: max_chars // 2]
    tail = text[-max_chars // 2 :]
    return head + "\n\n# ... FILE TRUNCATED FOR PROMPT BUDGET ...\n\n" + tail


def internal_nodes_only(graph) -> List[str]:
    return [n for n in graph.nodes() if not str(n).startswith("external:")]


def select_high_innode_files(graph, top_k: int = 10, min_in_degree: int = 1) -> List[Dict[str, Any]]:
    internal = internal_nodes_only(graph)

    ranked: List[Dict[str, Any]] = []
    for node in internal:
        indeg = graph.in_degree(node)
        if indeg >= min_in_degree:
            ranked.append(
                {
                    "file": node,
                    "in_degree": indeg,
                    "out_degree": graph.out_degree(node),
                    "imported_by": sorted(
                        n for n in graph.predecessors(node)
                        if not str(n).startswith("external:")
                    ),
                    "imports": sorted(
                        n for n in graph.successors(node)
                        if not str(n).startswith("external:")
                    ),
                }
            )

    ranked.sort(key=lambda x: (-x["in_degree"], x["file"]))
    return ranked[:top_k]

def summarize_file_with_llm(
    client: OpenAI,
    *,
    model: str,
    repo_path: str,
    rel_path: str,
    language: str,
    in_degree: int,
    out_degree: int,
    imported_by: List[str],
    imports: List[str],
) -> Dict[str, Any]:
    abs_path = os.path.join(repo_path, rel_path)
    file_text = read_file_safely(abs_path)

    prompt = f"""
    You are summarizing an INTERNAL source file from a software repository.
    
    Goal:
    Write a concise technical summary for one high in-degree internal file.
    This is for repository due diligence / architecture documentation.
    
    Rules:
    - Focus only on THIS file.
    - Treat only repo files as internal dependencies.
    - Ignore external libraries/frameworks except where essential to explain the file's purpose.
    - Do not speculate beyond the provided code and dependency context.
    - If the file content is truncated, mention that only if it affects confidence.
    - Return VALID JSON only.
    
    Return this exact schema:
    {{
      "file": "relative/path.py",
      "role": "1-2 sentence description of the file's responsibility",
      "key_responsibilities": ["...", "..."],
      "important_internal_dependencies": ["..."],
      "important_internal_dependents": ["..."],
      "why_central": "Why many internal files depend on it",
      "risk_notes": ["..."],
      "confidence": "high|medium|low"
    }}
    
    Repository-relative file: {rel_path}
    Language: {language}
    In-degree: {in_degree}
    Out-degree: {out_degree}
    
    Internal files importing this file:
    {json.dumps(imported_by, indent=2)}
    
    Internal files this file imports:
    {json.dumps(imports, indent=2)}
    
    File contents:
    ```{language.lower()}
    {file_text}
    """.strip()
    response = client.responses.create(
        model=model,
        input=prompt,
    )

    text = response.output_text.strip()

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    return {
        "file": rel_path,
        "role": "Failed to parse model output as JSON.",
        "key_responsibilities": [],
        "important_internal_dependencies": imports,
        "important_internal_dependents": imported_by,
        "why_central": "",
        "risk_notes": [text[:1000]],
        "confidence": "low",
    }

def summarize_repo(repo_path: str, *, model: str, top_k: int, min_in_degree: int) -> Dict[str, Any]:
    client = OpenAI()

    graph = build_dep_graph(repo_path)
    lang_info = language_breakdown(repo_path)
    per_file_lang = lang_info.get("per_file", {})

    selected = select_high_innode_files(
        graph,
        top_k=top_k,
        min_in_degree=min_in_degree,
)
    summaries = []
    for item in selected:
        rel_path = item["file"]
        language = per_file_lang.get(rel_path, "Unknown")

        summary = summarize_file_with_llm(
            client,
            model=model,
            repo_path=repo_path,
            rel_path=rel_path,
            language=language,
            in_degree=item["in_degree"],
            out_degree=item["out_degree"],
            imported_by=item["imported_by"],
            imports=item["imports"],
        )

        summary["_metrics"] = {
            "in_degree": item["in_degree"],
            "out_degree": item["out_degree"],
        }
        summaries.append(summary)

    return {
        "repo_path": os.path.abspath(repo_path),
        "model": model,
        "top_k": top_k,
        "min_in_degree": min_in_degree,
        "summaries": summaries,
    }

def write_markdown_report(result: Dict[str, Any], out_path: str) -> None:
    lines: List[str] = []
    lines.append("# High In-Node Internal File Summaries\n")
    lines.append(f"Repository: {result['repo_path']}\n")
    lines.append(f"Model: {result['model']}\n")

    for s in result["summaries"]:
        lines.append(f"## `{s['file']}`")
        lines.append(f"**Role:** {s.get('role', '')}")
        lines.append("")
        lines.append(
            f"**Graph metrics:** in-degree={s['_metrics']['in_degree']}, "
            f"out-degree={s['_metrics']['out_degree']}"
        )
        lines.append("")

        kr = s.get("key_responsibilities", [])
        if kr:
            lines.append("**Key responsibilities**")
            for item in kr:
                lines.append(f"- {item}")
            lines.append("")

        deps = s.get("important_internal_dependencies", [])
        if deps:
            lines.append("**Important internal dependencies**")
            for item in deps:
                lines.append(f"- `{item}`")
            lines.append("")

        dependents = s.get("important_internal_dependents", [])
        if dependents:
            lines.append("**Important internal dependents**")
            for item in dependents:
                lines.append(f"- `{item}`")
            lines.append("")

        why = s.get("why_central", "")
        if why:
            lines.append(f"**Why central:** {why}")
            lines.append("")

        risks = s.get("risk_notes", [])
        if risks:
            lines.append("**Risk notes**")
            for item in risks:
                lines.append(f"- {item}")
            lines.append("")

        lines.append(f"**Confidence:** {s.get('confidence', 'unknown')}")
        lines.append("")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def main() -> None:
    parser = argparse.ArgumentParser(
    description="Generate LLM summaries for high in-degree internal files."
    )
    parser.add_argument("repo_path", help="Path to repo to analyze")
    parser.add_argument(
    "--model",
    default=DEFAULT_MODEL,
    help=f"OpenAI model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
    "--top-k",
    type=int,
    default=10,
    help="Number of high in-degree internal files to summarize",
    )
    parser.add_argument(
    "--min-in-degree",
    type=int,
    default=1,
    help="Minimum in-degree required to summarize a file",
    )
    parser.add_argument(
    "--json-out",
    default="high_innode_summaries.json",
    help="Path to JSON output file",
    )
    parser.add_argument(
    "--md-out",
    default="high_innode_summaries.md",
    help="Path to Markdown output file",
    )
    args = parser.parse_args()

    if not os.path.isdir(args.repo_path):
        print(f"Error: '{args.repo_path}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    result = summarize_repo(
        args.repo_path,
        model=args.model,
        top_k=args.top_k,
        min_in_degree=args.min_in_degree,
    )

    with open(args.json_out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    write_markdown_report(result, args.md_out)

    print(f"Wrote JSON summaries to: {args.json_out}")
    print(f"Wrote Markdown report to: {args.md_out}")

    if __name__ == "main":
        main()
