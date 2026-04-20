"""
Base mixin for the ReAct agent loop shared by all agents.
"""
from __future__ import annotations

import json


class AgentLoopMixin:

    def _clean_json_response(self, content: str) -> str:
        """Strip markdown code fences that Mistral wraps around JSON responses."""
        content = content.strip()
        # Remove ```json ... ``` or ``` ... ```
        if content.startswith("```"):
            lines = content.split("\n")
            # Remove first line (```json or ```) and last line (```)
            lines = lines[1:] if lines[0].startswith("```") else lines
            lines = lines[:-1] if lines and lines[-1].strip() == "```" else lines
            content = "\n".join(lines).strip()
        return content

    """Provides _run_agent_loop for all agent subclasses."""

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
            content = response["choices"][0]["message"]["content"]

            # Strip markdown code fences that Mistral sometimes wraps around JSON
            stripped = content.strip()
            if stripped.startswith("```"):
                lines = stripped.split("\n")
                # drop opening fence (```json or ```) and closing fence (```)
                inner = lines[1:] if lines[0].startswith("```") else lines
                if inner and inner[-1].strip() == "```":
                    inner = inner[:-1]
                stripped = "\n".join(inner).strip()
            else:
                stripped = stripped

            try:
                parsed = json.loads(self._clean_json_response(content))
                if parsed.get("tool") == "finish":
                    return parsed.get("answer")

                tool_name = parsed.get("tool")
                tool_args = parsed.get("args", {})

                if tool_name in tools:
                    tool_result = tools[tool_name](**tool_args)
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {"role": "user", "content": f"Tool result: {json.dumps(tool_result)}"}
                    )
                else:
                    return stripped  # unknown tool → treat as final answer

            except json.JSONDecodeError:
                return stripped  # prose response → treat as final answer

        return messages[-1]["content"]  # max iterations hit
