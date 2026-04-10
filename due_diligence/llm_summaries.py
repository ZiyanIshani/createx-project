#!/usr/bin/env python3

from __future__ import annotations
import argparse
import json
import os
import sys
from typing import Any, Dict, List
import requests
import subprocess

sys.path.insert(0, os.path.dirname(__file__))

from repo_ingestion.file_tree import language_breakdown
from static_analysis.dep_graph import build_dep_graph


MAX_FILE_CHARS = 8000
DEFAULT_MODEL = "llama3"


# ------------------------
# FILE READING
# ------------------------
def read_file_safely(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except:
        return ""


# ------------------------
# GIT METADATA
# ------------------------
def get_git_metadata(repo_path: str, file_path: str):
    try:
        full_path = os.path.join(repo_path, file_path)

        authors = subprocess.check_output(
            ["git", "-C", repo_path, "log", "--pretty=format:%an", "--", full_path],
            text=True
        ).splitlines()

        if not authors:
            return {}

        top_authors = {}
        for a in authors:
            top_authors[a] = top_authors.get(a, 0) + 1

        last_modified = subprocess.check_output(
            ["git", "-C", repo_path, "log", "-1", "--pretty=format:%cd", "--", full_path],
            text=True
        )

        first_commit = subprocess.check_output(
            ["git", "-C", repo_path, "log", "--reverse", "-1", "--pretty=format:%cd", "--", full_path],
            text=True
        )

        return {
            "top_authors": sorted(
                [{"name": k, "commit_count": v} for k, v in top_authors.items()],
                key=lambda x: -x["commit_count"]
            )[:3],
            "last_modified": last_modified,
            "first_commit": first_commit
        }

    except:
        return {}


# ------------------------
# QUALITY HEURISTICS
# ------------------------
def compute_quality_metrics(file_text: str):
    lines = file_text.splitlines()
    num_lines = len(lines)

    todo_count = sum(1 for l in lines if "TODO" in l or "FIXME" in l)

    return {
        "num_lines": num_lines,
        "todo_count": todo_count,
        "large_file": num_lines > 500,
    }


# ------------------------
# COMPATIBILITY CHECK
# ------------------------
def detect_platform_risks(file_text: str):
    risks = []

    if "C:\\" in file_text:
        risks.append("Windows-specific paths")

    if "chmod" in file_text or "#!/bin/bash" in file_text:
        risks.append("Unix-specific commands")

    if "brew install" in file_text:
        risks.append("macOS-specific dependency")

    return risks


# ------------------------
# FILE SELECTION
# ------------------------
def internal_nodes_only(graph):
    return [n for n in graph.nodes() if not str(n).startswith("external:")]


def select_high_innode_files(graph, top_k=5):
    internal = internal_nodes_only(graph)

    ranked = []
    for node in internal:
        ranked.append({
            "file": node,
            "in_degree": graph.in_degree(node),
            "out_degree": graph.out_degree(node)
        })

    ranked.sort(key=lambda x: -x["in_degree"])
    return ranked[:top_k]


# ------------------------
# LLM CALL
# ------------------------
def summarize_file_with_llm(file_data, model="llama3"):

    prompt = f"""
Analyze this code file and return JSON.

File: {file_data['file']}
Language: {file_data['language']}

Also consider:
- who wrote it
- when it was modified
- code quality
- platform compatibility

Return JSON:
{{
  "file": "...",
  "role": "...",
  "quality_summary": "...",
  "ownership_summary": "...",
  "compatibility_summary": "...",
  "possible_provenance_flags": ["..."]
}}
"""

    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False
        }
    )

    text = response.json().get("response", "")

    try:
        return json.loads(text)
    except:
        return {"raw_output": text}


# ------------------------
# MAIN PIPELINE
# ------------------------
def summarize_repo(repo_path):

    graph = build_dep_graph(repo_path)
    lang_info = language_breakdown(repo_path)
    per_file_lang = lang_info.get("per_file", {})

    selected = select_high_innode_files(graph)

    results = []

    for item in selected:
        file_path = item["file"]
        abs_path = os.path.join(repo_path, file_path)

        file_text = read_file_safely(abs_path)

        git_meta = get_git_metadata(repo_path, file_path)
        quality = compute_quality_metrics(file_text)
        platform = detect_platform_risks(file_text)

        file_data = {
            "file": file_path,
            "language": per_file_lang.get(file_path, "unknown"),
            "git": git_meta,
            "quality": quality,
            "platform": platform,
            "code": file_text[:2000]
        }

        summary = summarize_file_with_llm(file_data)

        results.append(summary)

    return results


# ------------------------
# ENTRY
# ------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_path")
    parser.add_argument("--out", default="enhanced_summaries.json")

    args = parser.parse_args()

    result = summarize_repo(args.repo_path)

    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)

    print("Done. Enhanced summaries saved.")


if __name__ == "__main__":
    main()