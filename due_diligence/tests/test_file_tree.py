"""Tests for repo_ingestion/file_tree.py using a real pygit2 repo."""

from __future__ import annotations

import time

import pygit2
import pytest

from repo_ingestion.file_tree import detect_languages, discover_files, language_breakdown


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _sig(name: str = "Test", email: str = "test@test.com") -> pygit2.Signature:
    return pygit2.Signature(name, email, int(time.time()), 0)


@pytest.fixture()
def multi_lang_repo(tmp_path):
    """Repo with Python, JS, TS, Go, and Markdown files."""
    repo = pygit2.init_repository(str(tmp_path), bare=False)
    repo.set_head("refs/heads/main")

    files = {
        "main.py": "print('hello')\n",
        "app.js": "console.log('hi');\n",
        "types.ts": "export type Foo = string;\n",
        "main.go": "package main\n",
        "README.md": "# Test\n",
    }
    for name, content in files.items():
        (tmp_path / name).write_text(content)

    sig = _sig()
    index = repo.index
    index.read()
    for name in files:
        index.add(name)
    index.write()
    tree = index.write_tree()
    repo.create_commit("refs/heads/main", sig, sig, "Initial commit", tree, [])

    return tmp_path


@pytest.fixture()
def empty_repo(tmp_path):
    pygit2.init_repository(str(tmp_path), bare=False)
    return tmp_path


# ---------------------------------------------------------------------------
# discover_files
# ---------------------------------------------------------------------------

class TestDiscoverFiles:
    def test_returns_tracked_files(self, multi_lang_repo):
        files = discover_files(str(multi_lang_repo))
        assert "main.py" in files
        assert "app.js" in files
        assert "types.ts" in files
        assert "main.go" in files
        assert "README.md" in files

    def test_no_untracked_files(self, multi_lang_repo):
        # Create an untracked file
        (multi_lang_repo / "untracked.txt").write_text("untracked")
        files = discover_files(str(multi_lang_repo))
        assert "untracked.txt" not in files

    def test_empty_repo(self, empty_repo):
        assert discover_files(str(empty_repo)) == []

    def test_invalid_path(self, tmp_path):
        assert discover_files(str(tmp_path / "nonexistent")) == []

    def test_returns_list_of_strings(self, multi_lang_repo):
        files = discover_files(str(multi_lang_repo))
        assert isinstance(files, list)
        for f in files:
            assert isinstance(f, str)


# ---------------------------------------------------------------------------
# detect_languages
# ---------------------------------------------------------------------------

class TestDetectLanguages:
    def test_python_detection(self):
        summary, per_file = detect_languages(["main.py", "utils.py"])
        assert per_file["main.py"] == "Python"
        assert summary["Python"] == 2

    def test_multiple_languages(self):
        paths = ["a.py", "b.js", "c.ts", "d.go", "e.rs", "f.java"]
        summary, per_file = detect_languages(paths)
        assert per_file["a.py"] == "Python"
        assert per_file["b.js"] == "JavaScript"
        assert per_file["c.ts"] == "TypeScript"
        assert per_file["d.go"] == "Go"
        assert per_file["e.rs"] == "Rust"
        assert per_file["f.java"] == "Java"

    def test_unknown_extension(self):
        summary, per_file = detect_languages(["file.xyz"])
        assert per_file["file.xyz"] == "Unknown"

    def test_all_required_languages(self):
        ext_lang = {
            ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
            ".java": "Java", ".go": "Go", ".rs": "Rust",
            ".c": "C", ".cpp": "C++", ".cs": "C#", ".rb": "Ruby",
            ".php": "PHP", ".swift": "Swift", ".kt": "Kotlin", ".scala": "Scala",
            ".sh": "Shell", ".html": "HTML", ".css": "CSS",
            ".json": "JSON", ".yaml": "YAML", ".md": "Markdown",
        }
        paths = [f"file{ext}" for ext in ext_lang]
        _, per_file = detect_languages(paths)
        for ext, expected_lang in ext_lang.items():
            assert per_file[f"file{ext}"] == expected_lang

    def test_empty_list(self):
        summary, per_file = detect_languages([])
        assert summary == {}
        assert per_file == {}


# ---------------------------------------------------------------------------
# language_breakdown
# ---------------------------------------------------------------------------

class TestLanguageBreakdown:
    def test_returns_summary_and_per_file(self, multi_lang_repo):
        result = language_breakdown(str(multi_lang_repo))
        assert "summary" in result
        assert "per_file" in result

    def test_summary_counts_correct(self, multi_lang_repo):
        result = language_breakdown(str(multi_lang_repo))
        assert result["summary"].get("Python", 0) >= 1
        assert result["summary"].get("JavaScript", 0) >= 1

    def test_empty_repo(self, empty_repo):
        result = language_breakdown(str(empty_repo))
        assert result["summary"] == {}
        assert result["per_file"] == {}
