"""
tests/test_agent_loop.py — Unit tests for AgentLoopMixin._clean_json_response.
"""
import pytest
from llm.agents import AgentLoopMixin


class _Mixin(AgentLoopMixin):
    """Minimal concrete class so we can call the mixin method."""
    pass


@pytest.fixture
def mixin():
    return _Mixin()


def test_plain_json_returned_unchanged(mixin):
    payload = '{"tool": "finish", "answer": "ok"}'
    assert mixin._clean_json_response(payload) == payload


def test_json_fenced_with_language_tag(mixin):
    content = '```json\n{"tool": "finish", "answer": "ok"}\n```'
    result = mixin._clean_json_response(content)
    assert result == '{"tool": "finish", "answer": "ok"}'


def test_json_fenced_without_language_tag(mixin):
    content = '```\n{"tool": "finish", "answer": "ok"}\n```'
    result = mixin._clean_json_response(content)
    assert result == '{"tool": "finish", "answer": "ok"}'


def test_prose_preamble_with_fenced_json(mixin):
    content = (
        "Here is my analysis:\n"
        "```json\n"
        '{"tool": "finish", "answer": "done"}\n'
        "```"
    )
    result = mixin._clean_json_response(content)
    assert result == '{"tool": "finish", "answer": "done"}'


def test_prose_with_inline_json(mixin):
    content = 'Sure! Here is the JSON: {"tool": "finish", "answer": "yes"}'
    result = mixin._clean_json_response(content)
    assert result == '{"tool": "finish", "answer": "yes"}'


def test_no_json_returns_original(mixin):
    content = "This is just plain prose with no JSON at all."
    result = mixin._clean_json_response(content)
    assert result == content
