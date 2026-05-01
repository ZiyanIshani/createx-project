#!/usr/bin/env python3
"""
llm_summaries.py — experimental local-LLM summary generator.

Alternative to the Groq-based pipeline that targets locally hosted models
(e.g. Ollama with Gemma or LLaMA). Useful for fully air-gapped environments
where the Groq API is not accessible.

Unlike main.py, this script calls the local Ollama HTTP API directly and does
not use the ReAct agent loop. It is not integrated into the main CLI or web
dashboard and is intended as a standalone tool or starting point for local
LLM integration.

Default model: gemma3:1b (configurable via --model)
Default Ollama endpoint: http://localhost:11434/api/generate

Usage:
    python llm_summaries.py <repo_path> [--model NAME] [--output json|pretty]
"""
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
DEFAULT_MODEL = "gemma3:1b"


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
        # Use file_path relative to repo_path — do NOT join into an absolute/relative path
        # that git would reject when running with -C
        authors = subprocess.check_output(
            ["git", "-C", repo_path, "log", "--pretty=format:%an", "--", file_path],
            text=True, stderr=subprocess.DEVNULL
        ).splitlines()

        if not authors:
            return {}

        top_authors = {}
        for a in authors:
            top_authors[a] = top_authors.get(a, 0) + 1

        last_modified = subprocess.check_output(
            ["git", "-C", repo_path, "log", "-1", "--pretty=format:%cd", "--", file_path],
            text=True, stderr=subprocess.DEVNULL
        )

        first_commit = subprocess.check_output(
            ["git", "-C", repo_path, "log", "--reverse", "-1", "--pretty=format:%cd", "--", file_path],
            text=True, stderr=subprocess.DEVNULL
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
def summarize_file_with_llm(file_data, model=DEFAULT_MODEL):

    git = file_data.get("git", {})
    quality = file_data.get("quality", {})
    authors = ", ".join(a["name"] for a in git.get("top_authors", []))

    prompt = (
        f"You are a code reviewer. Analyze the file below and respond with ONLY a JSON object "
        f"— no markdown, no explanation, just the raw JSON.\n\n"
        f"File: {file_data['file']}\n"
        f"Language: {file_data['language']}\n"
        f"Top authors: {authors or 'unknown'}\n"
        f"Last modified: {git.get('last_modified', 'unknown')}\n"
        f"Lines: {quality.get('num_lines', '?')}, TODOs: {quality.get('todo_count', 0)}\n"
        f"Platform risks: {file_data.get('platform', [])}\n\n"
        f"Code (first 2000 chars):\n{file_data.get('code', '')}\n\n"
        f"Return this exact JSON schema:\n"
        f'{{"role":"<1 sentence>","quality_summary":"<1 sentence>","ownership_summary":"<1 sentence>",'
        f'"compatibility_summary":"<1 sentence>","possible_provenance_flags":[]}}'
    )

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=120,
        )
        response.raise_for_status()
        text = response.json().get("response", "").strip()
    except Exception as e:
        return {"raw_output": f"Ollama request failed: {e}"}

    # Strip markdown code fences if the model wrapped the JSON
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        return json.loads(text)
    except Exception:
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
        summary["file"] = file_path  # guarantee file key is always present

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
