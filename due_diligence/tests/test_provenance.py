"""Tests for llm/agents/provenance.py"""
from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock

import pytest

from llm.agents.provenance import ProvenanceAgent


def _make_client(response_content: str) -> MagicMock:
    client = MagicMock()
    client.chat.return_value = {
        "choices": [{"message": {"content": response_content}}]
    }
    return client


class TestHeuristicScan:
    def setup_method(self):
        self.agent = ProvenanceAgent(MagicMock())

    def test_clean_file_not_suspicious(self):
        content = "def add(a, b):\n    return a + b\n"
        result = self.agent.heuristic_scan("add.py", content)
        assert result["suspicious"] is False
        assert result["signals"] == []

    def test_url_in_comment_flagged(self):
        content = "# https://stackoverflow.com/questions/12345\nx = 1\n"
        result = self.agent.heuristic_scan("file.py", content)
        assert result["suspicious"] is True
        assert any("URL" in s for s in result["signals"])

    def test_generic_names_flagged(self):
        content = "def foo(bar, baz):\n    temp = bar + baz\n    return temp\n"
        result = self.agent.heuristic_scan("file.py", content)
        assert result["suspicious"] is True
        assert any("placeholder" in s.lower() for s in result["signals"])

    def test_attribution_comment_flagged(self):
        content = "# taken from some blog post\ndef compute(x):\n    return x * 2\n"
        result = self.agent.heuristic_scan("file.py", content)
        assert result["suspicious"] is True
        assert any("Attribution" in s for s in result["signals"])

    def test_style_shift_flagged(self):
        # First half: short lines; second half: very long lines
        short = ["x = 1"] * 10
        long = ["very_long_variable_name_that_makes_line_very_long = some_function_call_here()"] * 10
        content = "\n".join(short + long)
        result = self.agent.heuristic_scan("file.py", content)
        assert result["suspicious"] is True
        assert any("Style shift" in s for s in result["signals"])


class TestLLMAnalyze:
    def test_high_risk_aggregation(self):
        answer = {
            "file": "stolen.py",
            "provenance_risk": "high",
            "evidence": ["URL in comment", "Generic names"],
            "suspicious_sections": [
                {"start_line": 1, "end_line": 10, "reason": "copied"},
                {"start_line": 20, "end_line": 30, "reason": "copied"},
                {"start_line": 40, "end_line": 50, "reason": "copied"},
            ],
        }
        client = _make_client(json.dumps({"tool": "finish", "answer": answer}))
        agent = ProvenanceAgent(client)
        result = agent.llm_analyze("stolen.py", "x = 1\n" * 10, ["URL found"])
        assert result["provenance_risk"] in ("medium", "high")
        assert result["file"] == "stolen.py"

    def test_parse_error_returns_low_risk_evidence(self):
        client = _make_client("not json")
        agent = ProvenanceAgent(client)
        result = agent.llm_analyze("file.py", "x = 1\n", [])
        # Should not raise; result has required keys
        assert "provenance_risk" in result
        assert "evidence" in result


class TestScanFiles:
    def test_skips_non_suspicious_files(self):
        client = MagicMock()
        agent = ProvenanceAgent(client)

        with tempfile.TemporaryDirectory() as tmpdir:
            clean_path = os.path.join(tmpdir, "clean.py")
            with open(clean_path, "w") as f:
                f.write("def compute(value):\n    return value * 2\n")

            results = agent.scan_files(["clean.py"], tmpdir, {"clean.py": "Python"})

        # LLM should not have been called for clean file
        client.chat.assert_not_called()
        assert results == []

    def test_suspicious_file_triggers_llm(self):
        answer = {
            "provenance_risk": "medium",
            "evidence": ["URL in comment"],
            "suspicious_sections": [{"start_line": 1, "end_line": 1, "reason": "url"}],
        }
        client = _make_client(json.dumps({"tool": "finish", "answer": answer}))
        agent = ProvenanceAgent(client)

        with tempfile.TemporaryDirectory() as tmpdir:
            suspicious_path = os.path.join(tmpdir, "suspect.py")
            with open(suspicious_path, "w") as f:
                f.write("# https://stackoverflow.com/a/12345\nfoo = 1\n")

            results = agent.scan_files(["suspect.py"], tmpdir, {"suspect.py": "Python"})

        assert client.chat.called
        assert len(results) == 1
        assert results[0]["provenance_risk"] == "medium"
