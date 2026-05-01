"""
commit_parser.py — standalone utility for counting commits per author.

Quick-start alternative to the full pipeline when you only need a contributor
summary. Uses pygit2 to walk git history without any subprocess calls.

Usage:
    Edit the repo path at the bottom of this file, then run:
        python commit_parser.py

Note: the hardcoded path at the bottom of this file must be updated before use.
This script is intentionally separate from the main due_diligence package.
"""
from collections import defaultdict, Counter
import pygit2

def commits_per_email(repo_path: str, ref: str = "HEAD", drop_merges: bool = False):
    """
    Count commits per author email in the given repository.

    Args:
        repo_path: Absolute or relative path to the git repository.
        ref: Git ref to walk from (branch name, tag, or commit SHA). Default: HEAD.
        drop_merges: If True, skip merge commits (parents > 1). Default: False.

    Returns:
        List of (commit_count, display_name, email) tuples sorted descending by count.
        Display name is the most frequently used name for that email address.
    """
    git_dir = pygit2.discover_repository(repo_path)
    repo = pygit2.Repository(git_dir)

    target = repo.revparse_single(ref).id
    walker = repo.walk(target, pygit2.GIT_SORT_TOPOLOGICAL | pygit2.GIT_SORT_TIME)

    counts = Counter()
    names_seen = defaultdict(Counter)

    for commit in walker:
        if drop_merges and len(commit.parents) > 1:
            continue

        email = (commit.author.email or "unknown").strip().lower()
        name = (commit.author.name or "unknown").strip()

        counts[email] += 1
        names_seen[email][name] += 1

    # build nice display: pick most common name for each email
    rows = []
    for email, n in counts.most_common():
        best_name, _ = names_seen[email].most_common(1)[0]
        rows.append((n, best_name, email))

    return rows

rows = commits_per_email("/Users/Ziyan/Documents/GitHub/Malware-Analysis")
for n, name, email in rows[:20]:
    print(f"{n:6d}  {name} <{email}>")