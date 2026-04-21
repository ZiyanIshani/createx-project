"""
Base mixin for the ReAct agent loop shared by all agents.
"""
from __future__ import annotations

import json
import re
import time


class AgentLoopMixin:
    """Provides _run_agent_loop for all agent subclasses."""

    def _clean_json_response(self, content: str) -> str:
        """
        Extract JSON from an LLM response that may contain markdown fences,
        prose preamble, or both. Handles all Mistral formatting quirks.
        """
        content = content.strip()

        # Case 1: response contains a ```json ... ``` or ``` ... ``` block
        # anywhere in the string (Mistral often puts prose before the block)
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
        if match:
            return match.group(1).strip()

        # Case 2: response starts with { or [ — already raw JSON
        if content.startswith("{") or content.startswith("["):
            return content

        # Case 3: find the first { and last } and extract that substring
        # handles cases like "Sure! Here is the JSON: {...}"
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            return content[start:end + 1]

        # Case 4: no JSON found — return as-is and let json.loads fail naturally
        return content

    def _run_agent_loop(
        self,
        system_prompt: str,
        initial_user_message: str,
        tools: dict,
        max_iterations: int = 10,
    ):
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": initial_user_message},
        ]

        for _ in range(max_iterations):
            response = self.client.chat(messages)
            raw_content = response["choices"][0]["message"]["content"]
            cleaned = self._clean_json_response(raw_content)

            try:
                parsed = json.loads(cleaned)

                if parsed.get("tool") == "finish":
                    return parsed.get("answer")

                tool_name = parsed.get("tool")
                tool_args = parsed.get("args", {})

                if tool_name in tools:
                    tool_result = tools[tool_name](**tool_args)
                    messages.append({"role": "assistant", "content": raw_content})
                    messages.append(
                        {"role": "user", "content": f"Tool result: {json.dumps(tool_result)}"}
                    )
                else:
                    # Unknown tool name — treat the cleaned content as final answer
                    return cleaned

            except json.JSONDecodeError:
                # Model returned prose with no parseable JSON — treat as final answer
                return cleaned

        # Max iterations reached — return last message content
        return self._clean_json_response(messages[-1]["content"])
