"""
tests/test_subscriptions.py — Tests for SubscriptionDetector.
"""
import os
import pytest
from llm.agents.subscriptions import SubscriptionDetector


@pytest.fixture
def detector():
    return SubscriptionDetector()


def _write_tmp(tmp_path, filename, content):
    p = tmp_path / filename
    p.write_text(content)
    return str(p.name), str(tmp_path)


def test_detects_aws_from_python_import(tmp_path, detector):
    rel, repo = _write_tmp(tmp_path, "cloud.py", "from aws_cdk import core\n")
    matches = detector.scan(repo, {rel: "Python"})
    services = {m["service"] for m in matches}
    assert "aws" in services


def test_detects_stripe_from_js_require(tmp_path, detector):
    rel, repo = _write_tmp(tmp_path, "pay.js", "const stripe = require('stripe');\n")
    matches = detector.scan(repo, {rel: "JavaScript"})
    services = {m["service"] for m in matches}
    assert "stripe" in services


def test_detects_twilio_from_url_in_comment(tmp_path, detector):
    rel, repo = _write_tmp(
        tmp_path, "notify.py",
        "# See https://api.twilio.com/2010-04-01/Accounts for docs\n"
    )
    matches = detector.scan(repo, {rel: "Python"})
    services = {m["service"] for m in matches}
    assert "twilio" in services


def test_no_matches_for_clean_file(tmp_path, detector):
    rel, repo = _write_tmp(tmp_path, "utils.py", "def add(a, b):\n    return a + b\n")
    matches = detector.scan(repo, {rel: "Python"})
    assert matches == []


def test_summarize_deduplicates_across_files(detector):
    matches = [
        {
            "service": "stripe",
            "category": "Payments",
            "tier": "pay-as-you-go",
            "file": "billing.py",
            "line": 1,
            "signal_type": "import",
            "matched_text": "import stripe",
        },
        {
            "service": "stripe",
            "category": "Payments",
            "tier": "pay-as-you-go",
            "file": "checkout.py",
            "line": 5,
            "signal_type": "string",
            "matched_text": "stripe_client = stripe.Client(key=STRIPE_KEY)",
        },
    ]
    summary = detector.summarize(matches)
    assert summary["service_count"] == 1
    stripe_entry = summary["services"][0]
    assert stripe_entry["service"] == "stripe"
    assert stripe_entry["reference_count"] == 2
    assert set(stripe_entry["files"]) == {"billing.py", "checkout.py"}
