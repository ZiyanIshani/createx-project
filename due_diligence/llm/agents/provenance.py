"""
llm/agents/provenance.py — Provenance risk agent.

Answers: does this code look like it was copied from online?
Heuristic pass runs first; LLM only called on files that pass the threshold.
"""
from __future__ import annotations

import json
import os
import re

from llm.agents import AgentLoopMixin
from llm.prompts import SYSTEM_PROVENANCE

_GENERIC_NAMES = re.compile(r"\b(foo|bar|baz|temp|tmp|test123)\b", re.IGNORECASE)
_URL_PATTERN = re.compile(r"https?://")
_ATTRIBUTION_PATTERN = re.compile(
    r"#\s*(from|source:|via|credit|taken from)", re.IGNORECASE
)
_CHUNK_SIZE = 200


class ProvenanceAgent(AgentLoopMixin):
    def __init__(self, client) -> None:
        self.client = client

    def heuristic_scan(self, file_path: str, file_content: str) -> dict:
        """Cheap text checks — no LLM call."""
        signals = []
        lines = file_content.splitlines()

        # URLs in comments
        for i, line in enumerate(lines, 1):
            if _URL_PATTERN.search(line) and line.strip().startswith("#"):
                signals.append(f"Line {i}: URL found in comment")
                break  # one signal is enough

        # Generic placeholder names
        if _GENERIC_NAMES.search(file_content):
            signals.append("Generic placeholder names found (foo/bar/baz/temp/tmp/test123)")

        # Attribution lines
        for i, line in enumerate(lines, 1):
            if _ATTRIBUTION_PATTERN.search(line):
                signals.append(f"Line {i}: Attribution comment detected")
                break

        # Style shift: compare avg line length of first half vs second half
        if len(lines) >= 4:
            mid = len(lines) // 2
            first_half = [l for l in lines[:mid] if l.strip()]
            second_half = [l for l in lines[mid:] if l.strip()]
            if first_half and second_half:
                avg_first = sum(len(l) for l in first_half) / len(first_half)
                avg_second = sum(len(l) for l in second_half) / len(second_half)
                if avg_first > 0:
                    diff_pct = abs(avg_second - avg_first) / avg_first
                    if diff_pct > 0.30:
                        signals.append(
                            f"Style shift detected: avg line length changes by "
                            f"{diff_pct:.0%} between file halves"
                        )

        return {"suspicious": len(signals) > 0, "signals": signals}

    def llm_analyze(
        self,
        file_path: str,
        file_content: str,
        heuristic_signals: list[str],
    ) -> dict:
        """Send file to LLM in chunks, aggregate results."""
        lines = file_content.splitlines()
        chunks = []
        for start in range(0, len(lines), _CHUNK_SIZE):
            chunk_lines = lines[start : start + _CHUNK_SIZE]
            chunks.append((start + 1, start + len(chunk_lines), "\n".join(chunk_lines)))

        all_evidence: list[str] = list(heuristic_signals)
        all_suspicious_sections: list[dict] = []

        for start_line, end_line, chunk_text in chunks:
            message = (
                f"File: {file_path} (lines {start_line}-{end_line})\n"
                f"Heuristic signals already detected: {json.dumps(heuristic_signals)}\n\n"
                f"Source code chunk:\n```\n{chunk_text}\n```\n\n"
                "Analyze this chunk for provenance risk and call finish with your assessment."
            )
            raw = self._run_agent_loop(SYSTEM_PROVENANCE, message, {"finish": lambda answer: answer})
            chunk_result = self._parse_chunk_result(raw, file_path, start_line)

            all_evidence.extend(chunk_result.get("evidence", []))
            for section in chunk_result.get("suspicious_sections", []):
                # Adjust line numbers to be absolute
                section = dict(section)
                section["start_line"] = section.get("start_line", 1) + start_line - 1
                section["end_line"] = section.get("end_line", start_line) + start_line - 1
                all_suspicious_sections.append(section)

        # Determine overall risk
        if len(all_suspicious_sections) >= 3 or len(all_evidence) >= 4:
            risk = "high"
        elif all_suspicious_sections or len(all_evidence) >= 2:
            risk = "medium"
        else:
            risk = "low"

        # Deduplicate evidence
        seen = set()
        deduped_evidence = []
        for e in all_evidence:
            if e not in seen:
                seen.add(e)
                deduped_evidence.append(e)

        return {
            "file": file_path,
            "provenance_risk": risk,
            "evidence": deduped_evidence,
            "suspicious_sections": all_suspicious_sections,
        }

    def _parse_chunk_result(self, raw, file_path: str, start_line: int) -> dict:
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
                    "evidence": [],
                    "suspicious_sections": [],
                    "parse_error": True,
                }
        else:
            return {"risk_level": "unknown", "risk_summary": "No response.", "evidence": [], "suspicious_sections": [], "parse_error": True}

    def scan_files(
        self,
        file_paths: list[str],
        repo_path: str,
        per_file_languages: dict[str, str],
    ) -> list[dict]:
        """Run heuristic then LLM scan; return only files with risk != 'low'."""
        results = []
        for rel_path in file_paths:
            abs_path = os.path.join(repo_path, rel_path)
            try:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
            except OSError:
                continue

            heuristic = self.heuristic_scan(rel_path, content)
            if not heuristic["suspicious"]:
                continue

            result = self.llm_analyze(rel_path, content, heuristic["signals"])
            if result["provenance_risk"] != "low":
                results.append(result)

        return results
