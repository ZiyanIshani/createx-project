"""
client.py — Groq API client for the due diligence LLM layer.

Groq is OpenAI-compatible so the request/response format is identical
to the OpenAI SDK. We use raw requests to avoid extra dependencies.

Free tier: 30 RPM, 14,400 RPD on llama-3.1-8b-instant.
"""
from __future__ import annotations

import os
import time
import requests


GROQ_API_BASE = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "llama-3.1-8b-instant"
PLACEHOLDER_KEY = "REPLACE_WITH_YOUR_GROQ_API_KEY"


class GroqConnectionError(Exception):
    pass


class GroqClient:
    """
    Lightweight HTTP client for the Groq chat completions API.

    Uses raw requests rather than the openai SDK to avoid extra dependencies.
    The API is OpenAI-compatible — same endpoint format, same request/response shape.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
    ):
        """
        Args:
            api_key: Groq API key. Falls back to the GROQ_API_KEY environment variable.
            model: Model identifier to use for all requests. Default: llama-3.1-8b-instant.
        """
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", PLACEHOLDER_KEY)
        self.model = model

    def _headers(self) -> dict:
        """Return the Authorization and Content-Type headers for every request."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 2048,
        max_retries: int = 3,
    ) -> dict:
        """
        Send messages to Groq and return the raw response dict.
        Uses OpenAI-compatible /chat/completions endpoint.
        Retries up to max_retries times on 429 with exponential backoff.
        Raises GroqConnectionError on failure.
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        url = f"{GROQ_API_BASE}/chat/completions"

        for attempt in range(max_retries):
            try:
                response = requests.post(
                    url,
                    headers=self._headers(),
                    json=payload,
                    timeout=60,
                )
            except requests.exceptions.RequestException as e:
                raise GroqConnectionError(f"Groq request failed: {e}") from e

            if response.status_code == 200:
                return response.json()

            if response.status_code == 429:
                wait = 20 * (attempt + 1)  # 20s, 40s, 60s
                time.sleep(wait)
                continue

            raise GroqConnectionError(
                f"Groq returned HTTP {response.status_code} after "
                f"{attempt + 1} attempts: {response.text[:300]}"
            )

        raise GroqConnectionError(
            f"Groq returned 429 after {max_retries} retries. "
            f"Free tier limit reached — try again in a minute."
        )

    def is_available(self) -> bool:
        """
        Return True if the Groq API is reachable and the API key is valid.

        A 429 (rate limited) response is treated as available because the key
        is authenticated — the caller should still proceed and let the retry
        logic in chat() handle the backoff.

        Returns:
            True if the API responds with 200 or 429, False on any other status
            or network error.
        """
        try:
            response = requests.post(
                f"{GROQ_API_BASE}/chat/completions",
                headers=self._headers(),
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1,
                },
                timeout=10,
            )
            return response.status_code in (200, 429)
        except Exception:
            return False
