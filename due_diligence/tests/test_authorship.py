"""Tests for llm/agents/authorship.py"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from llm.agents.authorship import AuthorshipAgent


def _make_client(response_content: str) -> MagicMock:
    client = MagicMock()
    client.chat.return_value = {
        "choices": [{"message": {"content": response_content}}]
    }
    return client


def _finish_response(answer: dict) -> str:
    return json.dumps({"tool": "finish", "answer": answer})


class TestAuthorshipAgentAnalyze:
    def test_single_inactive_contributor_critical_risk(self):
        answer = {
            "file": "src/core.py",
            "contributor_count": 1,
            "risk_level": "critical",
            "risk_summary": "Sole contributor is inactive. Critical knowledge loss.",
            "contributors": [{"email": "a@example.com", "recency_score": 0.0, "recency_label": "inactive"}],
        }
        client = _make_client(_finish_response(answer))
        agent = AuthorshipAgent(client)

        result = agent.analyze(
            "src/core.py",
            ["a@example.com"],
            {"a@example.com": 0.0},
        )

        assert result["risk_level"] == "critical"
        assert result["file"] == "src/core.py"
        assert result["contributor_count"] == 1

    def test_active_contributor_low_risk(self):
        answer = {
            "file": "src/utils.py",
            "contributor_count": 1,
            "risk_level": "low",
            "risk_summary": "Active contributor with recent commits.",
            "contributors": [{"email": "b@example.com", "recency_score": 1.0, "recency_label": "active"}],
        }
        client = _make_client(_finish_response(answer))
        agent = AuthorshipAgent(client)

        result = agent.analyze(
            "src/utils.py",
            ["b@example.com"],
            {"b@example.com": 1.0},
        )

        assert result["risk_level"] == "low"

    def test_parse_error_returns_fallback(self):
        client = _make_client("this is not json at all")
        agent = AuthorshipAgent(client)

        result = agent.analyze(
            "src/broken.py",
            ["c@example.com"],
            {"c@example.com": 0.5},
        )

        assert result["file"] == "src/broken.py"
        assert result["contributor_count"] == 1
        assert result["parse_error"] is True

    def test_analyze_critical_files_sorted_by_risk(self):
        responses = [
            _finish_response({
                "file": "a.py",
                "contributor_count": 1,
                "risk_level": "low",
                "risk_summary": "Fine.",
                "contributors": [],
            }),
            _finish_response({
                "file": "b.py",
                "contributor_count": 1,
                "risk_level": "critical",
                "risk_summary": "Danger.",
                "contributors": [],
            }),
        ]
        call_count = 0

        def side_effect(messages, **kwargs):
            nonlocal call_count
            resp = responses[call_count % len(responses)]
            call_count += 1
            return {"choices": [{"message": {"content": resp}}]}

        client = MagicMock()
        client.chat.side_effect = side_effect
        agent = AuthorshipAgent(client)

        dep_graph_metrics = {
            "fragile_files": [{"file": "a.py", "in_degree": 5}, {"file": "b.py", "in_degree": 3}]
        }
        bus_factor_data = {"a.py": ["x@x.com"], "b.py": ["y@y.com"]}
        recency_map = {"x@x.com": 1.0, "y@y.com": 0.0}

        results = agent.analyze_critical_files(dep_graph_metrics, bus_factor_data, recency_map, top_n=2)

        assert len(results) == 2
        assert results[0]["risk_level"] == "critical"
        assert results[1]["risk_level"] == "low"
