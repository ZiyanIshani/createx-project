#!/usr/bin/env python3
"""
server.py — Flask web server for the due diligence dashboard.

Usage:
    python server.py <repo_path> [--port 5000] [--ref HEAD]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading

sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, render_template, send_file, abort, jsonify

from main import _run_pipeline

app = Flask(__name__)

# Global state set at startup
_repo_path: str = ""
_ref: str = "HEAD"
_use_llm: bool = False
_result: dict | None = None
_repo_name: str = ""
_repo_url: str = ""

# LLM summary state — computed in background
_llm_summaries: list | None = None   # None = not done yet, [] = done but empty
_llm_lock = threading.Lock()


def _run_llm_in_background(repo_path: str) -> None:
    global _llm_summaries
    try:
        from llm_summaries import summarize_repo
        result = summarize_repo(repo_path)
        summaries = result if isinstance(result, list) else result.get("summaries", [])
    except Exception as exc:
        print(f"Warning: LLM summaries failed: {exc}", file=sys.stderr)
        summaries = []
    with _llm_lock:
        _llm_summaries = summaries


def _get_repo_info(repo_path: str) -> tuple[str, str]:
    """Return (repo_name, remote_url) derived from git remote, falling back to directory name."""
    try:
        url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            cwd=repo_path, text=True, stderr=subprocess.DEVNULL,
        ).strip()
        name = url.rstrip("/").split("/")[-1]
        if name.endswith(".git"):
            name = name[:-4]
        # Normalise SSH URLs (git@github.com:user/repo) to HTTPS for display
        display_url = url
        if display_url.startswith("git@"):
            display_url = display_url.replace(":", "/").replace("git@", "https://")
        if display_url.endswith(".git"):
            display_url = display_url[:-4]
        return name, display_url
    except Exception:
        return os.path.basename(repo_path), repo_path


@app.route("/")
def dashboard():
    global _result, _llm_summaries
    if _result is None:
        # Run fast pipeline (no LLM) so the page loads immediately
        _result = _run_pipeline(_repo_path, ref=_ref, use_llm=False)
        # Kick off LLM in background if enabled
        if _use_llm:
            _llm_summaries = None  # mark as pending
            t = threading.Thread(target=_run_llm_in_background, args=(_repo_path,), daemon=True)
            t.start()
    return render_template(
        "dashboard.html",
        data=_result,
        repo_name=_repo_name,
        repo_url=_repo_url,
        bus_data=_result.get("bus_data", {}),
        use_llm=_use_llm,
    )


@app.route("/llm-data")
def llm_data():
    """Polled by the dashboard to check if LLM summaries are ready."""
    with _llm_lock:
        if _llm_summaries is None:
            return jsonify({"status": "pending"})
        return jsonify({"status": "done", "summaries": _llm_summaries})


@app.route("/graph-data")
def graph_data():
    global _result
    if _result is None:
        _result = _run_pipeline(_repo_path, ref=_ref)
    bus_data = _result.get("bus_data", {})

    nodes, edges = [], []
    seen_nodes = set()

    for file_path, emails in bus_data.items():
        if file_path not in seen_nodes:
            nodes.append({"data": {
                "id": file_path,
                "label": file_path.split("/")[-1],
                "full_path": file_path,
                "kind": "file",
            }})
            seen_nodes.add(file_path)
        for email in emails:
            if email not in seen_nodes:
                nodes.append({"data": {
                    "id": email,
                    "label": email.split("@")[0],
                    "full_path": email,
                    "kind": "person",
                }})
                seen_nodes.add(email)
            edges.append({"data": {"source": email, "target": file_path}})

    return jsonify({"nodes": nodes, "edges": edges})


@app.route("/graph-image")
def graph_image():
    if _result is None:
        abort(404)
    path = _result.get("contributor_file_graph", "")
    if not path or not os.path.isfile(path):
        abort(404)
    return send_file(path, mimetype="image/png")


@app.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


@app.route("/refresh")
def refresh():
    global _result, _llm_summaries
    _result = None
    _llm_summaries = None
    from flask import redirect, url_for
    return redirect(url_for("dashboard"))




def main() -> None:
    parser = argparse.ArgumentParser(description="Due diligence web dashboard.")
    parser.add_argument("repo_path", help="Path to the git repository to analyse.")
    parser.add_argument("--ref", default="HEAD", help="Git ref to analyse (default: HEAD).")
    parser.add_argument("--port", type=int, default=8080, help="Port to serve on (default: 8080).")
    parser.add_argument("--llm", action="store_true", help="Enable LLM summaries (requires OPENAI_API_KEY).")
    args = parser.parse_args()

    if not os.path.isdir(args.repo_path):
        print(f"Error: '{args.repo_path}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    global _repo_path, _ref, _use_llm, _repo_name, _repo_url
    _repo_path = os.path.abspath(args.repo_path)
    _ref = args.ref
    _use_llm = args.llm
    _repo_name, _repo_url = _get_repo_info(_repo_path)

    print(f"Starting dashboard for: {_repo_path}")
    print(f"Open http://localhost:{args.port} in your browser")
    print("(Note: port 5000 is reserved by macOS AirPlay — use 8080 or another port)")
    app.run(debug=False, port=args.port)


if __name__ == "__main__":
    main()
