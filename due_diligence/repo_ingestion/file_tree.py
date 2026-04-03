"""
file_tree.py — tracked-file discovery and language detection using pygit2.
"""

from __future__ import annotations

import os
from collections import defaultdict
from typing import Dict, List, Tuple

import pygit2


# ---------------------------------------------------------------------------
# Extension → language map
# ---------------------------------------------------------------------------

_EXT_TO_LANG: Dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".hxx": "C++",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".scala": "Scala",
    ".sc": "Scala",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".fish": "Shell",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "CSS",
    ".sass": "CSS",
    ".less": "CSS",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".md": "Markdown",
    ".markdown": "Markdown",
}


def _open_repo(repo_path: str) -> pygit2.Repository | None:
    try:
        return pygit2.Repository(repo_path)
    except pygit2.GitError:
        return None


def _resolve_head(repo: pygit2.Repository) -> pygit2.Commit | None:
    try:
        obj = repo.revparse_single("HEAD")
        if isinstance(obj, pygit2.Tag):
            obj = obj.peel(pygit2.Commit)
        return obj if isinstance(obj, pygit2.Commit) else None
    except (pygit2.GitError, KeyError):
        return None


# Directories and file extensions that are never meaningful source files.
# Filtered at discovery time so nothing downstream ever sees them.
_IGNORE_DIRS: frozenset[str] = frozenset({
    "__pycache__", ".git", "node_modules", ".venv", "venv",
    "env", ".env", "dist", "build", ".mypy_cache", ".pytest_cache",
    ".tox", ".eggs", "*.egg-info",
})

_IGNORE_EXTENSIONS: frozenset[str] = frozenset({
    ".pyc", ".pyo", ".pyd",          # Python bytecode
    ".class",                          # Java bytecode
    ".o", ".a", ".so", ".dylib",      # compiled objects / native libs
    ".exe", ".dll",                    # Windows binaries
    ".DS_Store",                       # macOS metadata
})

_IGNORE_FILENAMES: frozenset[str] = frozenset({
    ".DS_Store", "Thumbs.db", ".gitkeep",
})


def is_noise(entry_name: str, is_tree: bool) -> bool:
    """Return True if this entry should be excluded from analysis.

    Public so other modules (e.g. git_stats) can reuse the same filter.
    """
    if is_tree:
        return entry_name in _IGNORE_DIRS
    _, ext = os.path.splitext(entry_name)
    return ext.lower() in _IGNORE_EXTENSIONS or entry_name in _IGNORE_FILENAMES


def _collect_tree_paths(tree: pygit2.Tree, repo: pygit2.Repository, prefix: str = "") -> List[str]:
    """Recursively collect blob paths from a tree, skipping noise files."""
    paths: List[str] = []
    for entry in tree:
        entry_path = f"{entry.name}" if not prefix else f"{prefix}/{entry.name}"
        obj = repo.get(entry.id)
        if isinstance(obj, pygit2.Tree):
            if not is_noise(entry.name, is_tree=True):
                paths.extend(_collect_tree_paths(obj, repo, entry_path))
        elif isinstance(obj, pygit2.Blob):
            if not is_noise(entry.name, is_tree=False):
                paths.append(entry_path)
    return paths




def discover_files(repo_path: str) -> List[str]:
    """
    Return a list of relative file paths tracked by git at HEAD.
    Uses pygit2 HEAD tree traversal — no os.walk.
    Returns [] for empty or invalid repos.
    """
    repo = _open_repo(repo_path)
    if repo is None:
        return []

    head = _resolve_head(repo)
    if head is None:
        return []

    return _collect_tree_paths(head.tree, repo)


def detect_languages(
    file_paths: List[str],
) -> Tuple[Dict[str, int], Dict[str, str]]:
    """
    Given a list of relative file paths, return:
      summary  — {language: count}
      per_file — {path: language}

    Unknown extensions are labelled "Unknown".
    """
    summary: Dict[str, int] = defaultdict(int)
    per_file: Dict[str, str] = {}

    for path in file_paths:
        _, ext = os.path.splitext(path)
        lang = _EXT_TO_LANG.get(ext.lower(), "Unknown")
        per_file[path] = lang
        summary[lang] += 1

    return dict(summary), per_file


def language_breakdown(repo_path: str) -> Dict[str, object]:
    """
    Convenience wrapper.
    Returns {"summary": {language: count}, "per_file": {path: language}}.
    """
    paths = discover_files(repo_path)
    summary, per_file = detect_languages(paths)
    return {"summary": summary, "per_file": per_file}
