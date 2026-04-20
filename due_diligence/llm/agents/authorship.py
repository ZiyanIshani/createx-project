"""
llm/agents/authorship.py — Authorship risk agent.

Answers: who wrote the critical files, and are they still around?
"""
from __future__ import annotations

import json

from llm.agents import AgentLoopMixin
from llm.prompts import SYSTEM_AUTHORSHIP


_RECENCY_LABELS = {1.0: "active", 0.5: "semi-active", 0.0: "inactive"}
_RISK_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class AuthorshipAgent(AgentLoopMixin):
    def __init__(self, client) -> None:
        self.client = client

    def analyze(
        self,
        file_path: str,
        bus_factor_entry: list[str],
        contributor_recency_map: dict[str, float],
    ) -> dict:
        """Analyze authorship risk for a single file."""
        tools = {
            "get_contributors": lambda file_path: bus_factor_entry,
            "get_recency": lambda email: contributor_recency_map.get(email, 0.0),
            "finish": lambda answer: answer,
        }

        initial_message = (
            f"Analyze authorship risk for the file: {file_path}\n"
            f"Use get_contributors to see who contributed, then get_recency for each "
            f"contributor, then call finish with your structured assessment."
        )

        raw = self._run_agent_loop(SYSTEM_AUTHORSHIP, initial_message, tools)

        return self._parse_result(file_path, raw, bus_factor_entry, contributor_recency_map)

    def _parse_result(
        self,
        file_path: str,
        raw,
        bus_factor_entry: list[str],
        contributor_recency_map: dict[str, float],
    ) -> dict:
        """Parse LLM output into a typed dict, with fallback on parse error."""
        if isinstance(raw, dict):
            result = raw
        else:
            try:
                result = json.loads(raw) if isinstance(raw, str) else {}
            except (json.JSONDecodeError, TypeError):
                return {
                    "file": file_path,
                    "contributor_count": len(bus_factor_entry),
                    "risk_level": "unknown",
                    "risk_summary": "Could not parse LLM response.",
                    "contributors": [],
                    "parse_error": True,
                    "raw": str(raw),
                }

        # Ensure required fields are present
        contributors = result.get("contributors") or [
            {
                "email": email,
                "recency_score": contributor_recency_map.get(email, 0.0),
                "recency_label": _RECENCY_LABELS.get(
                    contributor_recency_map.get(email, 0.0), "unknown"
                ),
            }
            for email in bus_factor_entry
        ]

        return {
            "file": result.get("file", file_path),
            "contributor_count": result.get("contributor_count", len(bus_factor_entry)),
            "risk_level": result.get("risk_level", "unknown"),
            "risk_summary": result.get("risk_summary", ""),
            "contributors": contributors,
        }

    def analyze_critical_files(
        self,
        dep_graph_metrics: dict,
        bus_factor_data: dict,
        contributor_recency_map: dict[str, float],
        top_n: int = 5,
    ) -> list[dict]:
        """Analyze the top N fragile files and return results sorted by risk."""
        fragile = dep_graph_metrics.get("fragile_files", [])[:top_n]
        results = []
        for entry in fragile:
            file_path = entry["file"]
            bus_entry = bus_factor_data.get(file_path, [])
            result = self.analyze(file_path, bus_entry, contributor_recency_map)
            results.append(result)

        results.sort(key=lambda r: _RISK_ORDER.get(r.get("risk_level", "low"), 3))
        return results
