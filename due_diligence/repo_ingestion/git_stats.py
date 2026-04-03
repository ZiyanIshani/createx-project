"""
git_stats.py — contributor statistics using pygit2 (no subprocess).
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from typing import Dict, List, Tuple

import pygit2

from repo_ingestion.file_tree import is_noise


def _month_range(start: str, end: str) -> list[str]:
    """Generate YYYY-MM strings from start to end, inclusive."""
    sy, sm = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    result: list[str] = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        result.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return result


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


def commit_velocity(
    repo_path: str, ref: str = "HEAD"
) -> Dict[str, object]:
    """
    Compute commit frequency and code churn (lines added/removed) bucketed
    by calendar month.  Returns gap-filled month arrays suitable for charting.
    """
    repo = _open_repo(repo_path)
    if repo is None:
        return _empty_velocity()

    head = _resolve_ref(repo, ref)
    if head is None:
        return _empty_velocity()

    monthly_commits: Dict[str, int] = defaultdict(int)
    monthly_added: Dict[str, int] = defaultdict(int)
    monthly_removed: Dict[str, int] = defaultdict(int)
    first_ts: int | None = None
    last_ts: int | None = None
    total = 0

    for commit in repo.walk(head.id, pygit2.GIT_SORT_TOPOLOGICAL):
        ts = commit.author.time
        dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        month_key = dt.strftime("%Y-%m")

        monthly_commits[month_key] += 1
        total += 1

        if first_ts is None or ts < first_ts:
            first_ts = ts
        if last_ts is None or ts > last_ts:
            last_ts = ts

        try:
            if commit.parents:
                diff = commit.parents[0].tree.diff_to_tree(commit.tree)
            else:
                empty_oid = repo.TreeBuilder().write()
                empty_tree = repo.get(empty_oid)
                diff = empty_tree.diff_to_tree(commit.tree)

            stats = diff.stats
            monthly_added[month_key] += stats.insertions
            monthly_removed[month_key] += stats.deletions
        except Exception:
            pass

    if not monthly_commits:
        return _empty_velocity()

    all_months_raw = sorted(monthly_commits.keys())
    all_months = _month_range(all_months_raw[0], all_months_raw[-1])

    first_date = (
        datetime.datetime.fromtimestamp(first_ts, tz=datetime.timezone.utc).strftime("%Y-%m-%d")
        if first_ts else None
    )
    last_date = (
        datetime.datetime.fromtimestamp(last_ts, tz=datetime.timezone.utc).strftime("%Y-%m-%d")
        if last_ts else None
    )

    return {
        "months": all_months,
        "commits_per_month": [monthly_commits.get(m, 0) for m in all_months],
        "lines_added_per_month": [monthly_added.get(m, 0) for m in all_months],
        "lines_removed_per_month": [monthly_removed.get(m, 0) for m in all_months],
        "total_commits": total,
        "first_commit_date": first_date,
        "last_commit_date": last_date,
    }


def _empty_velocity() -> Dict[str, object]:
    return {
        "months": [],
        "commits_per_month": [],
        "lines_added_per_month": [],
        "lines_removed_per_month": [],
        "total_commits": 0,
        "first_commit_date": None,
        "last_commit_date": None,
    }


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
