"""
llm/agents/quality.py — Code quality agent.

Answers: does this code meet our standards?
"""
from __future__ import annotations

import json
import os

from llm.agents import AgentLoopMixin
from llm.prompts import DEFAULT_STANDARDS, SYSTEM_QUALITY

_CHUNK_SIZE = 150
_OVERLAP = 20


def _grade(error_count: float) -> str:
    if error_count == 0:
        return "A"
    elif error_count <= 2:
        return "B"
    elif error_count <= 5:
        return "C"
    elif error_count <= 10:
        return "D"
    else:
        return "F"


class QualityAgent(AgentLoopMixin):
    def __init__(self, client) -> None:
        self.client = client

    def load_standards(self, standards_path: str | None) -> str:
        """Read standards file from disk; fall back to DEFAULT_STANDARDS."""
        if standards_path is None:
            return DEFAULT_STANDARDS
        try:
            with open(standards_path, "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return DEFAULT_STANDARDS

    def analyze_file(
        self,
        file_path: str,
        file_content: str,
        language: str,
        standards_text: str,
    ) -> dict:
        """Analyze a single file against the standards, chunking if needed."""
        lines = file_content.splitlines()
        chunks = []
        start = 0
        while start < len(lines):
            end = min(start + _CHUNK_SIZE, len(lines))
            chunks.append((start + 1, end, "\n".join(lines[start:end])))
            if end == len(lines):
                break
            start = end - _OVERLAP  # overlapping window

        all_violations: list[dict] = []
        summaries: list[str] = []

        for chunk_start, chunk_end, chunk_text in chunks:
            message = (
                f"File: {file_path} (language: {language}, lines {chunk_start}-{chunk_end})\n\n"
                f"Coding standards:\n{standards_text}\n\n"
                f"Source code (line numbers start at {chunk_start}):\n"
                f"```\n{chunk_text}\n```\n\n"
                "Evaluate this code chunk against the standards. "
                "Call finish with your violations list and summary."
            )
            raw = self._run_agent_loop(
                SYSTEM_QUALITY,
                message,
                {"finish": lambda answer: answer},
            )
            chunk_result = self._parse_chunk_result(raw)
            for v in chunk_result.get("violations", []):
                all_violations.append(v)
            if chunk_result.get("summary"):
                summaries.append(chunk_result["summary"])

        # Deduplicate violations by line number proximity (±5 lines)
        deduped = self._deduplicate_violations(all_violations)

        # Grade calculation: errors + 0.5 * warnings
        error_count = sum(
            1.0 if v.get("severity") == "error" else (0.5 if v.get("severity") == "warning" else 0)
            for v in deduped
        )
        hard_errors = sum(1 for v in deduped if v.get("severity") == "error")

        return {
            "file": file_path,
            "language": language,
            "overall_grade": _grade(error_count),
            "violation_count": len(deduped),
            "violations": deduped,
            "summary": " ".join(summaries) if summaries else "No issues found.",
        }

    def _parse_chunk_result(self, raw) -> dict:
        if isinstance(raw, dict):
            return raw
        elif isinstance(raw, str):
            try:
                result = json.loads(self._clean_json_response(raw))
                return result
            except (json.JSONDecodeError, AttributeError):
                return {
                    "risk_level": "unknown",
                    "risk_summary": raw[:300] if raw else "No response from model.",
                    "violations": [],
                    "summary": "",
                    "parse_error": True,
                }
        else:
            return {"risk_level": "unknown", "risk_summary": "No response.", "violations": [], "summary": "", "parse_error": True}

    def _deduplicate_violations(self, violations: list[dict]) -> list[dict]:
        """Remove duplicate violations within ±5 lines of each other."""
        if not violations:
            return []
        seen: list[dict] = []
        for v in violations:
            line = v.get("line", 0)
            duplicate = any(
                abs(s.get("line", 0) - line) <= 5 and s.get("rule") == v.get("rule")
                for s in seen
            )
            if not duplicate:
                seen.append(v)
        return seen

    def analyze_critical_files(
        self,
        fragile_files: list[dict],
        repo_path: str,
        per_file_languages: dict[str, str],
        standards_path: str | None = None,
    ) -> list[dict]:
        """Analyze fragile files and return results sorted by violation_count descending."""
        standards_text = self.load_standards(standards_path)
        results = []
        for entry in fragile_files:
            file_path = entry["file"]
            abs_path = os.path.join(repo_path, file_path)
            try:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
            except OSError:
                continue

            language = per_file_languages.get(file_path, "unknown")
            result = self.analyze_file(file_path, content, language, standards_text)
            results.append(result)

        results.sort(key=lambda r: r.get("violation_count", 0), reverse=True)
        return results
