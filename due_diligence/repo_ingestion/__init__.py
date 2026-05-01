"""
repo_ingestion — git repository ingestion layer.

Provides contributor statistics, bus factor analysis, commit velocity, file
discovery, and language detection — all via pygit2 with no subprocess calls.

Public API:
    from repo_ingestion import (
        commits_per_email,        # commit counts per author email
        contributor_timeline,     # monthly commit histogram per author
        bus_factor_data,          # files → list of contributing emails
        contributor_recency_score,# augment contributor rows with recency (0/0.5/1.0)
        commit_velocity,          # monthly commits + lines added/removed
        discover_files,           # list of git-tracked file paths
        detect_languages,         # extension-based language classification
        language_breakdown,       # convenience wrapper → {summary, per_file}
    )
"""
from .git_stats import commits_per_email, contributor_timeline, bus_factor_data, contributor_recency_score, commit_velocity
from .file_tree import discover_files, detect_languages, language_breakdown

__all__ = [
    "commits_per_email",
    "contributor_timeline",
    "bus_factor_data",
    "contributor_recency_score",
    "commit_velocity",
    "discover_files",
    "detect_languages",
    "language_breakdown",
]
