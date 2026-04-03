"""
git_stats.py — contributor statistics using pygit2 (no subprocess).
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from typing import Dict, List, Tuple

import pygit2

from repo_ingestion.file_tree import is_noise


def _open_repo(repo_path: str) -> pygit2.Repository | None:
    try:
        return pygit2.Repository(repo_path)
    except pygit2.GitError:
        return None


def _resolve_ref(repo: pygit2.Repository, ref: str) -> pygit2.Commit | None:
    try:
        obj = repo.revparse_single(ref)
        if isinstance(obj, pygit2.Tag):
            obj = obj.peel(pygit2.Commit)
        return obj if isinstance(obj, pygit2.Commit) else None
    except (pygit2.GitError, KeyError):
        return None



def commits_per_email(
    repo_path: str, ref: str = "HEAD"
) -> List[Tuple[int, str, str]]:
    """Return [(commit_count, name, email)] sorted descending by count."""
    repo = _open_repo(repo_path)
    if repo is None:
        return []

    head = _resolve_ref(repo, ref)
    if head is None:
        return []

    counts: Dict[str, int] = defaultdict(int)
    names: Dict[str, str] = {}

    for commit in repo.walk(head.id, pygit2.GIT_SORT_TOPOLOGICAL):
        email = commit.author.email
        counts[email] += 1
        names[email] = commit.author.name

    return sorted(
        [(count, names[email], email) for email, count in counts.items()],
        key=lambda r: r[0],
        reverse=True,
    )


def contributor_timeline(
    repo_path: str, ref: str = "HEAD", bins: int | None = None
) -> Dict[str, Dict[str, int]]:
    """
    Return {email: {"YYYY-MM": count}} bucketed by calendar month.

    `bins` is accepted for API compatibility but ignored — months are the
    natural bucket size as required by the spec.
    """
    repo = _open_repo(repo_path)
    if repo is None:
        return {}

    head = _resolve_ref(repo, ref)
    if head is None:
        return {}

    timeline: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for commit in repo.walk(head.id, pygit2.GIT_SORT_TOPOLOGICAL):
        email = commit.author.email
        ts = commit.author.time  # unix timestamp
        dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        month_key = dt.strftime("%Y-%m")
        timeline[email][month_key] += 1

    # Convert inner defaultdicts to plain dicts
    return {email: dict(months) for email, months in timeline.items()}


def bus_factor_data(
    repo_path: str, ref: str = "HEAD"
) -> Dict[str, List[str]]:
    """
    Return {relative_file_path: [email, ...]} — all unique emails that have
    touched each tracked file via git blame.
    """
    repo = _open_repo(repo_path)
    if repo is None:
        return {}

    head = _resolve_ref(repo, ref)
    if head is None:
        return {}

    result: Dict[str, List[str]] = {}

    def _walk_tree(tree: pygit2.Tree, prefix: str = "") -> None:
        for entry in tree:
            path = f"{prefix}{entry.name}" if not prefix else f"{prefix}/{entry.name}"
            obj = repo.get(entry.id)
            if isinstance(obj, pygit2.Tree):
                if not is_noise(entry.name, is_tree=True):
                    _walk_tree(obj, path)
            elif isinstance(obj, pygit2.Blob):
                if is_noise(entry.name, is_tree=False):
                    continue
                try:
                    blame = repo.blame(path, newest_commit=head.id)
                    emails = {
                        repo.get(hunk.final_commit_id).author.email
                        for hunk in blame
                        if repo.get(hunk.final_commit_id) is not None
                    }
                    result[path] = sorted(emails)
                except pygit2.GitError:
                    result[path] = []

    _walk_tree(head.tree)
    return result


def contributor_recency_score(
    rows: List[Tuple[int, str, str]],
    repo_path: str | None = None,
    ref: str = "HEAD",
) -> List[Tuple[int, str, str, int | None, float]]:
    """
    Augment rows from `commits_per_email` with (last_commit_date, recency_score).

    last_commit_date: unix timestamp of most recent commit by that author
    recency_score:
        1.0  — last commit within 6 months
        0.5  — last commit within 6–18 months
        0.0  — older than 18 months

    If repo_path is None, last_commit_date will be None and score 0.0.
    """
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    six_months_ago = now - datetime.timedelta(days=183)
    eighteen_months_ago = now - datetime.timedelta(days=548)

    last_commit: Dict[str, int] = {}

    if repo_path is not None:
        repo = _open_repo(repo_path)
        if repo is not None:
            head = _resolve_ref(repo, ref)
            if head is not None:
                for commit in repo.walk(head.id, pygit2.GIT_SORT_TOPOLOGICAL):
                    email = commit.author.email
                    ts = commit.author.time
                    if email not in last_commit or ts > last_commit[email]:
                        last_commit[email] = ts

    augmented = []
    for count, name, email in rows:
        ts = last_commit.get(email)
        if ts is None:
            score = 0.0
        else:
            dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
            if dt >= six_months_ago:
                score = 1.0
            elif dt >= eighteen_months_ago:
                score = 0.5
            else:
                score = 0.0
        augmented.append((count, name, email, ts, score))

    return augmented
