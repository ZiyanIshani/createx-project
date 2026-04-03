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

sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, render_template, send_file, abort

from main import _run_pipeline

app = Flask(__name__)

# Global state set at startup
_repo_path: str = ""
_ref: str = "HEAD"
_result: dict | None = None
_repo_name: str = ""
_repo_url: str = ""


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
    global _result
    if _result is None:
        _result = _run_pipeline(_repo_path, ref=_ref)
    return render_template("dashboard.html", data=_result, repo_name=_repo_name, repo_url=_repo_url)


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
    _result = _run_pipeline(_repo_path, ref=_ref)
    from flask import redirect, url_for
    return redirect(url_for("dashboard"))




def main() -> None:
    parser = argparse.ArgumentParser(description="Due diligence web dashboard.")
    parser.add_argument("repo_path", help="Path to the git repository to analyse.")
    parser.add_argument("--ref", default="HEAD", help="Git ref to analyse (default: HEAD).")
    parser.add_argument("--port", type=int, default=8080, help="Port to serve on (default: 8080).")
    args = parser.parse_args()

    if not os.path.isdir(args.repo_path):
        print(f"Error: '{args.repo_path}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    global _repo_path, _ref, _repo_name, _repo_url
    _repo_path = os.path.abspath(args.repo_path)
    _ref = args.ref
    _repo_name, _repo_url = _get_repo_info(_repo_path)

    print(f"Starting dashboard for: {_repo_path}")
    print(f"Open http://localhost:{args.port} in your browser")
    print("(Note: port 5000 is reserved by macOS AirPlay — use 8080 or another port)")
    app.run(debug=False, port=args.port)


if __name__ == "__main__":
    main()
