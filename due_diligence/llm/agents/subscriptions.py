"""
llm/agents/subscriptions.py — Subscription service detector.

Heuristic scan (no LLM call) that identifies external SaaS/cloud services
referenced in the codebase — a signal for hidden ongoing costs.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from static_analysis.ast_parser import parse_file

KNOWN_SERVICES: dict[str, dict[str, str]] = {
    # Cloud Platforms
    "aws":          {"category": "Cloud",    "tier": "pay-as-you-go"},
    "amazonaws":    {"category": "Cloud",    "tier": "pay-as-you-go"},
    "azure":        {"category": "Cloud",    "tier": "pay-as-you-go"},
    "googleapis":   {"category": "Cloud",    "tier": "pay-as-you-go"},
    "gcloud":       {"category": "Cloud",    "tier": "pay-as-you-go"},

    # Observability / Monitoring
    "datadog":      {"category": "Monitoring",  "tier": "subscription"},
    "newrelic":     {"category": "Monitoring",  "tier": "subscription"},
    "sentry":       {"category": "Monitoring",  "tier": "freemium"},
    "honeycomb":    {"category": "Monitoring",  "tier": "subscription"},
    "grafana":      {"category": "Monitoring",  "tier": "freemium"},
    "pagerduty":    {"category": "Alerting",    "tier": "subscription"},

    # Data / Analytics
    "snowflake":    {"category": "Data",     "tier": "subscription"},
    "databricks":   {"category": "Data",     "tier": "subscription"},
    "segment":      {"category": "Data",     "tier": "subscription"},
    "mixpanel":     {"category": "Analytics","tier": "subscription"},
    "amplitude":    {"category": "Analytics","tier": "subscription"},
    "fivetran":     {"category": "Data",     "tier": "subscription"},

    # Payments
    "stripe":       {"category": "Payments", "tier": "pay-as-you-go"},
    "braintree":    {"category": "Payments", "tier": "pay-as-you-go"},
    "plaid":        {"category": "Payments", "tier": "subscription"},
    "adyen":        {"category": "Payments", "tier": "pay-as-you-go"},

    # Communication
    "twilio":       {"category": "Comms",    "tier": "pay-as-you-go"},
    "sendgrid":     {"category": "Comms",    "tier": "subscription"},
    "mailgun":      {"category": "Comms",    "tier": "subscription"},
    "intercom":     {"category": "Comms",    "tier": "subscription"},
    "zendesk":      {"category": "Support",  "tier": "subscription"},

    # Auth / Identity
    "auth0":        {"category": "Auth",     "tier": "subscription"},
    "okta":         {"category": "Auth",     "tier": "subscription"},
    "cognito":      {"category": "Auth",     "tier": "pay-as-you-go"},

    # Search
    "algolia":      {"category": "Search",   "tier": "subscription"},
    "elasticsearch":{"category": "Search",   "tier": "open-source/managed"},
    "pinecone":     {"category": "Search",   "tier": "subscription"},

    # AI / ML APIs
    "openai":       {"category": "AI",       "tier": "pay-as-you-go"},
    "anthropic":    {"category": "AI",       "tier": "pay-as-you-go"},
    "cohere":       {"category": "AI",       "tier": "pay-as-you-go"},
    "huggingface":  {"category": "AI",       "tier": "freemium"},

    # Infrastructure
    "cloudflare":   {"category": "Infra",    "tier": "freemium"},
    "fastly":       {"category": "Infra",    "tier": "pay-as-you-go"},
    "heroku":       {"category": "Infra",    "tier": "subscription"},
    "vercel":       {"category": "Infra",    "tier": "freemium"},
    "netlify":      {"category": "Infra",    "tier": "freemium"},

    # Database / Storage
    "mongodb":      {"category": "Database", "tier": "freemium"},
    "planetscale":  {"category": "Database", "tier": "freemium"},
    "supabase":     {"category": "Database", "tier": "freemium"},
    "redis":        {"category": "Database", "tier": "open-source/managed"},

    # Feature Flags / Experimentation
    "launchdarkly": {"category": "Feature Flags", "tier": "subscription"},
    "split":        {"category": "Feature Flags", "tier": "subscription"},

    # CRM / Sales
    "salesforce":   {"category": "CRM",      "tier": "subscription"},
    "hubspot":      {"category": "CRM",      "tier": "freemium"},
}

_URL_RE = re.compile(r"https?://[^\s\"']+")
_USAGE_KEYWORDS = re.compile(
    r"\.com|api\.|sdk|client|key|token|secret|endpoint|url", re.IGNORECASE
)


class SubscriptionDetector:
    """Heuristic scanner — no LLM call."""

    def scan(self, repo_path: str, per_file_languages: dict[str, str]) -> list[dict]:
        """
        Scan all files in per_file_languages and return raw match records.
        """
        matches: list[dict] = []

        for rel_path, language in per_file_languages.items():
            import os
            abs_path = os.path.join(repo_path, rel_path)

            try:
                with open(abs_path, "rb") as fh:
                    header = fh.read(1024)
                if b"\x00" in header:
                    continue  # binary file
                content = header.decode("utf-8", errors="replace")
                with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
            except OSError:
                continue

            lines = content.splitlines()

            # Signal A — Import/package names via parse_file
            parsed = parse_file(abs_path, language)
            for imp in parsed.get("imports", []):
                imp_lower = imp.lower()
                for svc, meta in KNOWN_SERVICES.items():
                    if svc in imp_lower:
                        matches.append({
                            "service": svc,
                            "category": meta["category"],
                            "tier": meta["tier"],
                            "file": rel_path,
                            "line": 0,
                            "signal_type": "import",
                            "matched_text": imp,
                        })

            # Signal B — URL patterns
            for i, line in enumerate(lines, 1):
                for url_match in _URL_RE.finditer(line):
                    url = url_match.group(0)
                    url_lower = url.lower()
                    for svc, meta in KNOWN_SERVICES.items():
                        if svc in url_lower:
                            matches.append({
                                "service": svc,
                                "category": meta["category"],
                                "tier": meta["tier"],
                                "file": rel_path,
                                "line": i,
                                "signal_type": "url",
                                "matched_text": line.strip(),
                            })

            # Signal C — String literals and comments with usage keywords
            for i, line in enumerate(lines, 1):
                line_lower = line.lower()
                for svc, meta in KNOWN_SERVICES.items():
                    pattern = re.compile(r"\b" + re.escape(svc) + r"\b", re.IGNORECASE)
                    if pattern.search(line) and _USAGE_KEYWORDS.search(line):
                        matches.append({
                            "service": svc,
                            "category": meta["category"],
                            "tier": meta["tier"],
                            "file": rel_path,
                            "line": i,
                            "signal_type": "string",
                            "matched_text": line.strip(),
                        })

        return matches

    def summarize(self, matches: list[dict]) -> dict:
        """
        Deduplicate raw matches into a structured summary grouped by service.
        """
        # Group by service
        by_service: dict[str, dict[str, Any]] = {}
        for m in matches:
            svc = m["service"]
            if svc not in by_service:
                by_service[svc] = {
                    "service": svc,
                    "category": m["category"],
                    "tier": m["tier"],
                    "files": set(),
                    "first_seen": m,
                }
            by_service[svc]["files"].add(m["file"])
            # Prefer import signals as "first_seen" (strongest signal)
            current_signal = by_service[svc]["first_seen"]["signal_type"]
            if m["signal_type"] == "import" and current_signal != "import":
                by_service[svc]["first_seen"] = m

        services = []
        for svc_data in by_service.values():
            files = sorted(svc_data["files"])
            first = svc_data["first_seen"]
            services.append({
                "service": svc_data["service"],
                "category": svc_data["category"],
                "tier": svc_data["tier"],
                "reference_count": len(files),
                "files": files,
                "first_seen": {
                    "file": first["file"],
                    "line": first["line"],
                    "signal_type": first["signal_type"],
                    "matched_text": first["matched_text"],
                },
            })

        services.sort(key=lambda s: s["reference_count"], reverse=True)

        by_category: dict[str, list[str]] = defaultdict(list)
        for s in services:
            by_category[s["category"]].append(s["service"])

        return {
            "service_count": len(services),
            "services": services,
            "by_category": dict(by_category),
            "raw_matches": matches,
        }
