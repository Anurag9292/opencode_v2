"""ContextBuilder: system prompt construction + AgentMessage -> LLM conversion.

pi origin:
  - `build_system_prompt` mirrors `buildSystemPrompt`
    (packages/coding-agent/src/core/system-prompt.ts): tools list + guidelines +
    project context + skills + date/cwd.
  - `convert_to_llm` mirrors `convertToLlm` (packages/coding-agent/src/core/messages.ts):
    map transcript messages to provider-shaped dicts.
  - `build` mirrors the assembly of `Context` inside `streamAssistantResponse`
    (packages/agent/src/agent-loop.ts).

Subtracted from pi: skills auto-loading, prompt templates, thinking budgets, and
extension `transformContext` hooks (left as an extension point below).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Callable

from .tools import ToolRegistry
from .types import LlmContext, Message


@dataclass
class ContextBuilder:
    cwd: str = "."
    custom_system_prompt: str | None = None
    context_files: list[tuple[str, str]] = field(default_factory=list)  # (path, content) e.g. AGENTS.md
    guidelines: list[str] = field(default_factory=lambda: ["Be concise.", "Show file paths clearly."])
    # Extension point mirroring pi's `transformContext` hook.
    transform_messages: Callable[[list[Message]], list[Message]] | None = None

    def build_system_prompt(self, registry: ToolRegistry) -> str:
        if self.custom_system_prompt is not None:
            base = self.custom_system_prompt
        else:
            tools_list = "\n".join(f"- {s['name']}: {s['description']}" for s in registry.schemas()) or "(none)"
            guidelines = "\n".join(f"- {g}" for g in self.guidelines)
            base = (
                "You are a coding assistant operating inside a minimal harness. "
                "You help by reading files, running commands, editing code, and writing files.\n\n"
                f"Available tools:\n{tools_list}\n\n"
                f"Guidelines:\n{guidelines}"
            )

        for path, content in self.context_files:
            base += f'\n\n<project_instructions path="{path}">\n{content}\n</project_instructions>'

        today = datetime.date.today().isoformat()
        base += f"\nCurrent date: {today}\nCurrent working directory: {self.cwd}"
        return base

    def convert_to_llm(self, messages: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "user":
                out.append({"role": "user", "content": message.content})
            elif message.role == "assistant":
                entry: dict[str, Any] = {"role": "assistant", "content": message.content}
                if message.tool_calls:
                    entry["tool_calls"] = [
                        {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": _json(tc.arguments)}}
                        for tc in message.tool_calls
                    ]
                out.append(entry)
            elif message.role == "tool_result":
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id,
                        "content": message.content,
                    }
                )
        return out

    def build(self, messages: list[Message], registry: ToolRegistry) -> LlmContext:
        if self.transform_messages is not None:
            messages = self.transform_messages(messages)
        return LlmContext(
            system_prompt=self.build_system_prompt(registry),
            messages=self.convert_to_llm(messages),
            tools=registry.schemas(),
        )


def _json(value: Any) -> str:
    import json

    return json.dumps(value)
