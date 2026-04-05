"""
test_coverage.py — detect test files and estimate test coverage by module.

Uses naming conventions and directory structure to identify test files,
then cross-references with the dependency graph to determine which source
modules have at least one test importing them.
"""

from __future__ import annotations

import os
import posixpath
import re
from typing import Dict, List, Set

from repo_ingestion.file_tree import language_breakdown

_TEST_DIR_NAMES: frozenset[str] = frozenset({
    "tests", "test", "__tests__", "spec", "specs",
})

_TEST_FILE_PATTERNS: list[re.Pattern] = [
    re.compile(r"^test_.*\.py$"),
    re.compile(r"^.*_test\.py$"),
    re.compile(r"^conftest\.py$"),
    re.compile(r"^.*\.test\.[jt]sx?$"),
    re.compile(r"^.*\.spec\.[jt]sx?$"),
    re.compile(r"^.*Test\.java$"),
    re.compile(r"^.*_test\.go$"),
    re.compile(r"^test_.*\.rs$"),
    re.compile(r"^.*_test\.rs$"),
]

_CODE_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx",
    ".java", ".go", ".rs", ".c", ".h", ".cpp", ".cc", ".cxx",
    ".hpp", ".hxx", ".cs", ".rb", ".php", ".swift", ".kt", ".kts",
    ".scala", ".sc",
})


def is_test_file(file_path: str) -> bool:
    """Determine if a file path is a test file based on naming conventions."""
    parts = posixpath.normpath(file_path).split("/")
    basename = parts[-1]

    for part in parts[:-1]:
        if part.lower() in _TEST_DIR_NAMES:
            return True

    for pattern in _TEST_FILE_PATTERNS:
        if pattern.match(basename):
            return True

    return False


def classify_files(all_files: List[str]) -> Dict[str, List[str]]:
    """Split files into test_files and source_files (code files only)."""
    test_files: List[str] = []
    source_files: List[str] = []

    for f in all_files:
        _, ext = os.path.splitext(f)
        if ext.lower() not in _CODE_EXTENSIONS:
            continue
        if is_test_file(f):
            test_files.append(f)
        else:
            source_files.append(f)

    return {"test_files": sorted(test_files), "source_files": sorted(source_files)}


def compute_test_coverage(repo_path: str, dep_graph=None) -> Dict[str, object]:
    """
    Compute test coverage metrics for the repository.

    When a dep_graph (NetworkX DiGraph) is provided, cross-references test
    file imports to determine which source modules are directly tested.
    """
    breakdown = language_breakdown(repo_path)
    all_files = list(breakdown.get("per_file", {}).keys())

    classified = classify_files(all_files)
    test_files = classified["test_files"]
    source_files = classified["source_files"]

    test_count = len(test_files)
    source_count = len(source_files)
    ratio = round(test_count / source_count, 3) if source_count > 0 else 0.0

    tested_set: Set[str] = set()
    if dep_graph is not None:
        test_set = set(test_files)
        for test_file in test_files:
            if test_file in dep_graph:
                for successor in dep_graph.successors(test_file):
                    if not successor.startswith("external:") and successor not in test_set:
                        tested_set.add(successor)

    source_set = set(source_files)
    tested_files = sorted(tested_set & source_set)
    untested_files = sorted(source_set - tested_set) if dep_graph is not None else []
    coverage_pct = round(len(tested_files) / source_count * 100, 1) if source_count > 0 else 0.0

    return {
        "test_file_count": test_count,
        "source_file_count": source_count,
        "test_to_source_ratio": ratio,
        "test_files": test_files,
        "untested_files": untested_files[:20],
        "tested_files": tested_files,
        "coverage_percent": coverage_pct,
    }
