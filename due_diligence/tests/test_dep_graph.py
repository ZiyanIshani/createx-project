"""Tests for static_analysis/dep_graph.py."""

from __future__ import annotations

import time

import networkx as nx
import pygit2
import pytest

from static_analysis.dep_graph import (
    architectural_risk_score,
    build_dep_graph,
    compute_metrics,
    resolve_import,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _sig() -> pygit2.Signature:
    return pygit2.Signature("Test", "test@test.com", int(time.time()), 0)


def _commit(repo, index, message, parents):
    tree = index.write_tree()
    return repo.create_commit("refs/heads/main", _sig(), _sig(), message, tree, parents)



@pytest.fixture()
def circular_repo(tmp_path):
    """
    Three-file Python repo with a circular dependency:
        a.py → b.py → c.py → a.py
    """
    repo = pygit2.init_repository(str(tmp_path), bare=False)
    repo.set_head("refs/heads/main")

    (tmp_path / "a.py").write_text("from b import something\n")
    (tmp_path / "b.py").write_text("from c import something\n")
    (tmp_path / "c.py").write_text("from a import something\n")

    index = repo.index
    index.read()
    for name in ["a.py", "b.py", "c.py"]:
        index.add(name)
    index.write()
    _commit(repo, index, "Initial commit", [])

    return tmp_path


@pytest.fixture()
def simple_repo(tmp_path):
    """Linear: a.py → b.py (no cycle)."""
    repo = pygit2.init_repository(str(tmp_path), bare=False)
    repo.set_head("refs/heads/main")

    (tmp_path / "a.py").write_text("from b import foo\n")
    (tmp_path / "b.py").write_text("x = 1\n")

    index = repo.index
    index.read()
    for name in ["a.py", "b.py"]:
        index.add(name)
    index.write()
    _commit(repo, index, "Initial commit", [])

    return tmp_path


# ---------------------------------------------------------------------------
# resolve_import
# ---------------------------------------------------------------------------

class TestResolveImport:
    def test_relative_import_found(self):
        all_files = ["utils/helpers.py", "main.py"]
        result = resolve_import("./helpers", "utils/main.py", all_files, "Python")
        assert result == "utils/helpers.py"

    def test_external_package(self):
        result = resolve_import("requests", "main.py", ["main.py"], "Python")
        assert result == "external:requests"

    def test_internal_by_stem(self):
        all_files = ["utils/helpers.py", "main.py"]
        result = resolve_import("helpers", "main.py", all_files, "Python")
        assert result == "utils/helpers.py"

    def test_empty_import_returns_none(self):
        assert resolve_import("", "main.py", [], "Python") is None

    def test_dotted_path_resolution(self):
        all_files = ["utils/helpers.py", "main.py"]
        result = resolve_import("utils.helpers", "main.py", all_files, "Python")
        assert result == "utils/helpers.py"


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------

class TestComputeMetrics:
    def test_basic_counts(self, simple_repo):
        graph = build_dep_graph(str(simple_repo))
        metrics = compute_metrics(graph)
        assert metrics["node_count"] >= 2
        assert metrics["edge_count"] >= 0
        assert isinstance(metrics["internal_file_count"], int)
        assert isinstance(metrics["external_dep_count"], int)

    def test_circular_dependency_detected(self, circular_repo):
        graph = build_dep_graph(str(circular_repo))
        metrics = compute_metrics(graph)
        sccs = metrics["circular_dependency_groups"]
        assert len(sccs) >= 1
        # The SCC should contain all three files
        all_in_scc = set()
        for group in sccs:
            all_in_scc.update(group)
        assert "a.py" in all_in_scc
        assert "b.py" in all_in_scc
        assert "c.py" in all_in_scc

    def test_no_circular_in_linear_repo(self, simple_repo):
        graph = build_dep_graph(str(simple_repo))
        metrics = compute_metrics(graph)
        assert metrics["circular_dependency_groups"] == []

    def test_metric_keys_present(self, simple_repo):
        graph = build_dep_graph(str(simple_repo))
        metrics = compute_metrics(graph)
        required_keys = {
            "node_count", "edge_count", "external_dep_count", "internal_file_count",
            "fragile_files", "circular_dependency_groups", "orphaned_files",
            "avg_in_degree", "max_in_degree", "top_external_deps",
        }
        assert required_keys.issubset(metrics.keys())


# ---------------------------------------------------------------------------
# architectural_risk_score
# ---------------------------------------------------------------------------

class TestArchitecturalRiskScore:
    def test_returns_score_and_reasons(self, simple_repo):
        graph = build_dep_graph(str(simple_repo))
        metrics = compute_metrics(graph)
        result = architectural_risk_score(metrics)
        assert "score" in result
        assert "reasons" in result
        assert isinstance(result["score"], int)
        assert 0 <= result["score"] <= 10
        assert isinstance(result["reasons"], list)
        assert len(result["reasons"]) >= 1

    def test_circular_repo_score_positive(self, circular_repo):
        graph = build_dep_graph(str(circular_repo))
        metrics = compute_metrics(graph)
        result = architectural_risk_score(metrics)
        assert result["score"] > 0

    def test_score_bounded(self):
        """Score must stay within 0–10 even for extreme metrics."""
        extreme_metrics = {
            "internal_file_count": 3,
            "circular_dependency_groups": [["a", "b"], ["c", "d"], ["e", "f"]],
            "max_in_degree": 100,
            "orphaned_files": ["x", "y", "z"],
        }
        result = architectural_risk_score(extreme_metrics)
        assert 0 <= result["score"] <= 10


# ---------------------------------------------------------------------------
# build_dep_graph
# ---------------------------------------------------------------------------

class TestBuildDepGraph:
    def test_returns_digraph(self, simple_repo):
        graph = build_dep_graph(str(simple_repo))
        assert isinstance(graph, nx.DiGraph)

    def test_internal_files_are_nodes(self, simple_repo):
        graph = build_dep_graph(str(simple_repo))
        assert "a.py" in graph.nodes
        assert "b.py" in graph.nodes

    def test_circular_edges_present(self, circular_repo):
        graph = build_dep_graph(str(circular_repo))
        nodes = set(graph.nodes)
        assert "a.py" in nodes
        assert "b.py" in nodes
        assert "c.py" in nodes
