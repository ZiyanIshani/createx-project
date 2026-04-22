#!/usr/bin/env python3
"""
server.py — Flask web server for the due diligence dashboard.

Usage (with landing page):
    python server.py [--port 8080] [--llm] [--top-n 3]

Usage (skip landing page, go straight to a repo):
    python server.py <repo_path> [--port 8080] [--llm]
"""

from __future__ import annotations

import argparse
import atexit
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, render_template, send_file, abort, jsonify, redirect, url_for, request

from main import _run_pipeline

app = Flask(__name__)

# Global state
_repo_path: str = ""
_ref: str = "HEAD"
_use_llm: bool = False
_top_n: int = 3
_result: dict | None = None
_repo_name: str = ""
_repo_url: str = ""
_cloned_tmp_dir: str | None = None  # temp dir for cloned repos; cleaned up on next analyze or exit

# Pre-configured local repos shown as quick-launch cards on the landing page.
# Each entry: {"name": display name, "path": absolute local path, "description": one-liner}
_LOCAL_REPOS: list[dict] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        display_url = url
        if display_url.startswith("git@"):
            display_url = display_url.replace(":", "/").replace("git@", "https://")
        if display_url.endswith(".git"):
            display_url = display_url[:-4]
        return name, display_url
    except Exception:
        return os.path.basename(repo_path), repo_path


def _cleanup_tmp() -> None:
    """Remove any previously cloned temp directory."""
    global _cloned_tmp_dir
    if _cloned_tmp_dir and os.path.isdir(_cloned_tmp_dir):
        try:
            shutil.rmtree(_cloned_tmp_dir)
        except Exception:
            pass
    _cloned_tmp_dir = None


def _prepare_repo(path_or_url: str) -> str:
    """
    If path_or_url looks like a URL, clone it into a fresh temp dir and return
    that path. Otherwise treat it as a local filesystem path and return as-is.
    Cleans up any previously cloned temp dir first.
    """
    global _cloned_tmp_dir

    is_url = path_or_url.startswith(("https://", "http://", "git@", "git://"))

    if not is_url:
        _cleanup_tmp()
        return os.path.abspath(path_or_url)

    _cleanup_tmp()
    tmp = tempfile.mkdtemp(prefix="duediligence_clone_")
    _cloned_tmp_dir = tmp

    print(f"Cloning {path_or_url} → {tmp} …", flush=True)
    try:
        subprocess.run(
            ["git", "clone", "--depth", "500", path_or_url, tmp],
            check=True,
            capture_output=False,
        )
    except subprocess.CalledProcessError as exc:
        _cleanup_tmp()
        raise RuntimeError(f"git clone failed: {exc}") from exc

    return tmp


def _set_active_repo(path: str) -> None:
    """Update all global state for a new active repo."""
    global _repo_path, _repo_name, _repo_url, _result
    _repo_path = path
    _repo_name, _repo_url = _get_repo_info(path)
    _result = None   # force re-run of pipeline


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Landing page — choose a repo to analyse."""
    return render_template("index.html", local_repos=_LOCAL_REPOS)


@app.route("/analyze", methods=["POST"])
def analyze():
    """
    Receive a repo selection from the landing page, prepare it (clone if URL),
    then redirect to the dashboard.
    """
    raw = request.form.get("repo", "").strip()
    if not raw:
        return redirect(url_for("index"))

    try:
        path = _prepare_repo(raw)
    except Exception as exc:
        # Re-render landing page with an error message
        return render_template("index.html", local_repos=_LOCAL_REPOS, error=str(exc)), 400

    _set_active_repo(path)
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    global _result
    if not _repo_path:
        return redirect(url_for("index"))
    if _result is None:
        _result = _run_pipeline(_repo_path, ref=_ref, use_llm=_use_llm, top_n=_top_n)
    return render_template(
        "dashboard.html",
        data=_result,
        repo_name=_repo_name,
        repo_url=_repo_url,
        bus_data=_result.get("bus_data", {}),
        subscriptions=_result.get("subscription_services", {}),
        llm_analysis=_result.get("llm_analysis", {}),
    )


@app.route("/graph-data")
def graph_data():
    global _result
    if _result is None:
        if not _repo_path:
            abort(404)
        _result = _run_pipeline(_repo_path, ref=_ref, top_n=_top_n)
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
    global _result
    _result = None
    return redirect(url_for("dashboard"))


@app.route("/home")
def home():
    """Back to the landing page."""
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Due diligence web dashboard.")
    parser.add_argument(
        "repo_path", nargs="?", default=None,
        help="Optional: path or GitHub URL of the repo to analyse. "
             "If omitted, a landing page lets you choose interactively.",
    )
    parser.add_argument("--ref", default="HEAD", help="Git ref to analyse (default: HEAD).")
    parser.add_argument("--port", type=int, default=8080, help="Port to serve on (default: 8080).")
    parser.add_argument("--llm", action="store_true", help="Enable LLM analysis via Groq (requires GROQ_API_KEY env var).")
    parser.add_argument(
        "--top-n", type=int, default=3,
        help="Number of critical files to run LLM analysis on (default: 3).",
    )
    args = parser.parse_args()

    global _ref, _use_llm, _top_n
    _ref = args.ref
    _use_llm = args.llm
    _top_n = args.top_n

    # Register cleanup so temp clones are removed when the server exits
    atexit.register(_cleanup_tmp)

    # Pre-populate the createx-project quick-launch card
    createx_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if os.path.isdir(os.path.join(createx_path, ".git")):
        _LOCAL_REPOS.append({
            "name": "createx-project",
            "path": createx_path,
            "description": "AI-powered technical due diligence platform (this repo)",
        })

    # If a repo was passed on the CLI, skip the landing page
    if args.repo_path:
        try:
            path = _prepare_repo(args.repo_path)
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        _set_active_repo(path)
        print(f"Starting dashboard for: {_repo_path}")
    else:
        print("No repo specified — starting with landing page.")

    print(f"Open http://localhost:{args.port} in your browser")
    app.run(debug=False, port=args.port)


if __name__ == "__main__":
    main()
