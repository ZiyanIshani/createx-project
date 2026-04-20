"""Tests for llm/agents/quality.py"""
from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock

import pytest

from llm.agents.quality import QualityAgent, _grade
from llm.prompts import DEFAULT_STANDARDS


def _make_client(response_content: str) -> MagicMock:
    client = MagicMock()
    client.chat.return_value = {
        "choices": [{"message": {"content": response_content}}]
    }
    return client


class TestGradeFunction:
    def test_zero_errors_is_A(self):
        assert _grade(0) == "A"

    def test_one_error_is_B(self):
        assert _grade(1) == "B"

    def test_two_errors_is_B(self):
        assert _grade(2) == "B"

    def test_three_errors_is_C(self):
        assert _grade(3) == "C"

    def test_six_errors_is_D(self):
        assert _grade(6) == "D"

    def test_eleven_errors_is_F(self):
        assert _grade(11) == "F"


class TestLoadStandards:
    def test_none_path_returns_default(self):
        agent = QualityAgent(MagicMock())
        result = agent.load_standards(None)
        assert result == DEFAULT_STANDARDS

    def test_missing_file_returns_default(self):
        agent = QualityAgent(MagicMock())
        result = agent.load_standards("/nonexistent/path/standards.md")
        assert result == DEFAULT_STANDARDS

    def test_reads_existing_file(self):
        agent = QualityAgent(MagicMock())
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# My Standards\n- No global variables\n")
            tmp_path = f.name
        try:
            result = agent.load_standards(tmp_path)
            assert "My Standards" in result
        finally:
            os.unlink(tmp_path)


class TestAnalyzeFile:
    def test_no_violations_grade_A(self):
        answer = {"violations": [], "summary": "Looks good."}
        client = _make_client(json.dumps({"tool": "finish", "answer": answer}))
        agent = QualityAgent(client)

        result = agent.analyze_file("src/clean.py", "x = 1\n", "Python", DEFAULT_STANDARDS)

        assert result["overall_grade"] == "A"
        assert result["violation_count"] == 0
        assert result["file"] == "src/clean.py"
        assert result["language"] == "Python"

    def test_errors_affect_grade(self):
        violations = [
            {"line": 5, "severity": "error", "rule": "naming", "description": "bad name"},
            {"line": 10, "severity": "error", "rule": "docstring", "description": "missing"},
            {"line": 15, "severity": "error", "rule": "bare_except", "description": "bare except"},
        ]
        answer = {"violations": violations, "summary": "Several errors."}
        client = _make_client(json.dumps({"tool": "finish", "answer": answer}))
        agent = QualityAgent(client)

        result = agent.analyze_file("src/bad.py", "x = 1\n", "Python", DEFAULT_STANDARDS)

        assert result["overall_grade"] == "C"
        assert result["violation_count"] == 3

    def test_deduplication_removes_nearby_violations(self):
        violations = [
            {"line": 10, "severity": "error", "rule": "naming", "description": "bad"},
            {"line": 12, "severity": "error", "rule": "naming", "description": "bad"},  # ±5 → dup
        ]
        answer = {"violations": violations, "summary": "Dup test."}
        client = _make_client(json.dumps({"tool": "finish", "answer": answer}))
        agent = QualityAgent(client)

        result = agent.analyze_file("src/dup.py", "x = 1\n", "Python", DEFAULT_STANDARDS)

        assert result["violation_count"] == 1  # deduplicated

    def test_parse_error_still_returns_result(self):
        client = _make_client("not json at all")
        agent = QualityAgent(client)

        result = agent.analyze_file("src/x.py", "x = 1\n", "Python", DEFAULT_STANDARDS)

        assert "file" in result
        assert "overall_grade" in result

    def test_long_file_chunked(self):
        # 200 lines should produce 2 chunks (150 + 50 with overlap)
        content = "\n".join(f"x_{i} = {i}" for i in range(200))
        answer = {"violations": [], "summary": "ok"}
        client = _make_client(json.dumps({"tool": "finish", "answer": answer}))
        agent = QualityAgent(client)

        result = agent.analyze_file("big.py", content, "Python", DEFAULT_STANDARDS)

        assert client.chat.call_count >= 2  # multiple chunks


class TestAnalyzeCriticalFiles:
    def test_sorts_by_violation_count_descending(self):
        responses = [
            json.dumps({"tool": "finish", "answer": {"violations": [], "summary": "clean"}}),
            json.dumps({"tool": "finish", "answer": {
                "violations": [
                    {"line": 1, "severity": "error", "rule": "r", "description": "d"},
                    {"line": 20, "severity": "error", "rule": "r2", "description": "d2"},
                ],
                "summary": "bad"
            }}),
        ]
        call_count = 0

        def side_effect(messages, **kwargs):
            nonlocal call_count
            resp = responses[call_count % len(responses)]
            call_count += 1
            return {"choices": [{"message": {"content": resp}}]}

        client = MagicMock()
        client.chat.side_effect = side_effect

        agent = QualityAgent(client)

        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ("clean.py", "bad.py"):
                with open(os.path.join(tmpdir, name), "w") as f:
                    f.write("x = 1\n")

            fragile = [{"file": "clean.py", "in_degree": 5}, {"file": "bad.py", "in_degree": 3}]
            results = agent.analyze_critical_files(
                fragile, tmpdir, {"clean.py": "Python", "bad.py": "Python"}
            )

        assert len(results) == 2
        assert results[0]["violation_count"] >= results[1]["violation_count"]
