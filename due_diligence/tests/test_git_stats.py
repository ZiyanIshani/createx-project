"""Tests for repo_ingestion/git_stats.py using a real pygit2 repo."""

from __future__ import annotations

import datetime
import time

import pygit2
import pytest

from repo_ingestion.git_stats import (
    bus_factor_data,
    commits_per_email,
    contributor_recency_score,
    contributor_timeline,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_signature(name: str, email: str, ts: int | None = None) -> pygit2.Signature:
    if ts is None:
        ts = int(time.time())
    return pygit2.Signature(name, email, ts, 0)


@pytest.fixture()
def minimal_repo(tmp_path):
    """A real git repo with two commits from two authors."""
    repo = pygit2.init_repository(str(tmp_path), bare=False)
    repo.set_head("refs/heads/main")

    # First commit — Alice
    alice = _make_signature("Alice", "alice@example.com", 1_700_000_000)
    file_a = tmp_path / "a.py"
    file_a.write_text("x = 1\n")

    index = repo.index
    index.read()
    index.add("a.py")
    index.write()
    tree = index.write_tree()
    c1 = repo.create_commit("refs/heads/main", alice, alice, "First commit", tree, [])

    # Second commit — Bob
    bob = _make_signature("Bob", "bob@example.com", 1_710_000_000)
    file_b = tmp_path / "b.py"
    file_b.write_text("y = 2\n")
    index.read()
    index.add("b.py")
    index.write()
    tree2 = index.write_tree()
    c2 = repo.create_commit("refs/heads/main", bob, bob, "Second commit", tree2, [c1])

    # Third commit — Alice again (recent)
    alice2 = _make_signature("Alice", "alice@example.com", int(time.time()) - 86400)
    file_a.write_text("x = 42\n")
    index.read()
    index.add("a.py")
    index.write()
    tree3 = index.write_tree()
    repo.create_commit("refs/heads/main", alice2, alice2, "Third commit", tree3, [c2])

    return tmp_path


@pytest.fixture()
def empty_repo(tmp_path):
    """A repo with no commits."""
    pygit2.init_repository(str(tmp_path), bare=False)
    return tmp_path


# ---------------------------------------------------------------------------
# commits_per_email
# ---------------------------------------------------------------------------

class TestCommitsPerEmail:
    def test_returns_correct_counts(self, minimal_repo):
        rows = commits_per_email(str(minimal_repo))
        counts = {email: count for count, name, email in rows}
        assert counts["alice@example.com"] == 2
        assert counts["bob@example.com"] == 1

    def test_sorted_descending(self, minimal_repo):
        rows = commits_per_email(str(minimal_repo))
        counts = [r[0] for r in rows]
        assert counts == sorted(counts, reverse=True)

    def test_empty_repo(self, empty_repo):
        assert commits_per_email(str(empty_repo)) == []

    def test_invalid_path(self, tmp_path):
        assert commits_per_email(str(tmp_path / "nonexistent")) == []


# ---------------------------------------------------------------------------
# contributor_timeline
# ---------------------------------------------------------------------------

class TestContributorTimeline:
    def test_contains_authors(self, minimal_repo):
        tl = contributor_timeline(str(minimal_repo))
        assert "alice@example.com" in tl
        assert "bob@example.com" in tl

    def test_month_format(self, minimal_repo):
        tl = contributor_timeline(str(minimal_repo))
        for email, months in tl.items():
            for key in months:
                # Must match YYYY-MM
                assert len(key) == 7
                assert key[4] == "-"

    def test_counts_positive(self, minimal_repo):
        tl = contributor_timeline(str(minimal_repo))
        for email, months in tl.items():
            for key, count in months.items():
                assert count > 0

    def test_empty_repo(self, empty_repo):
        assert contributor_timeline(str(empty_repo)) == {}


# ---------------------------------------------------------------------------
# bus_factor_data
# ---------------------------------------------------------------------------

class TestBusFactorData:
    def test_files_present(self, minimal_repo):
        data = bus_factor_data(str(minimal_repo))
        assert "a.py" in data
        assert "b.py" in data

    def test_alice_touched_a(self, minimal_repo):
        data = bus_factor_data(str(minimal_repo))
        assert "alice@example.com" in data["a.py"]

    def test_bob_touched_b(self, minimal_repo):
        data = bus_factor_data(str(minimal_repo))
        assert "bob@example.com" in data["b.py"]

    def test_empty_repo(self, empty_repo):
        assert bus_factor_data(str(empty_repo)) == {}


# ---------------------------------------------------------------------------
# contributor_recency_score
# ---------------------------------------------------------------------------

class TestContributorRecencyScore:
    def test_augments_rows(self, minimal_repo):
        rows = commits_per_email(str(minimal_repo))
        augmented = contributor_recency_score(rows, repo_path=str(minimal_repo))
        assert len(augmented) == len(rows)
        for row in augmented:
            assert len(row) == 5
            count, name, email, last_ts, score = row
            assert score in (0.0, 0.5, 1.0)

    def test_alice_recent(self, minimal_repo):
        rows = commits_per_email(str(minimal_repo))
        augmented = contributor_recency_score(rows, repo_path=str(minimal_repo))
        alice_rows = [r for r in augmented if r[2] == "alice@example.com"]
        assert alice_rows, "Alice should appear in augmented rows"
        assert alice_rows[0][4] == 1.0  # recent commit within 6 months

    def test_no_repo_path(self):
        rows = [(5, "Eve", "eve@example.com")]
        augmented = contributor_recency_score(rows)
        assert augmented[0][4] == 0.0  # no timestamp → score 0
