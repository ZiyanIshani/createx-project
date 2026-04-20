"""
llm/client.py — Thin wrapper around Ollama's OpenAI-compatible REST API.

Uses raw `requests` calls — no openai SDK dependency.
"""
from __future__ import annotations

import requests


class OllamaConnectionError(Exception):
    """Raised when the Ollama server is unreachable or returns a non-200 status."""


class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "mistral",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> dict:
        """POST to /v1/chat/completions and return the full response dict."""
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        try:
            resp = requests.post(url, json=payload, timeout=120)
        except requests.exceptions.ConnectionError as exc:
            raise OllamaConnectionError(
                f"Cannot reach Ollama at {self.base_url}: {exc}"
            ) from exc

        if resp.status_code != 200:
            raise OllamaConnectionError(
                f"Ollama returned HTTP {resp.status_code}: {resp.text[:200]}"
            )

        return resp.json()

    def is_available(self) -> bool:
        """Return True if Ollama is reachable and responding, False otherwise."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False
