"""Core data types for the harness.

Mirrors pi's message model (packages/ai/src/types.ts + packages/agent/src/types.ts)
but trimmed to the minimum needed to understand agent logic:

  - Only text content (pi also supports images/thinking blocks -> subtracted here).
  - One `Message` dataclass with optional fields instead of a discriminated union
    of user/assistant/toolResult (pi uses separate types -> merged here for brevity).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["user", "assistant", "tool_result"]

# Why the assistant stopped. Mirrors pi AssistantMessage.stopReason.
StopReason = Literal["end", "tool_use", "length", "error", "aborted"]


@dataclass
class ToolCall:
    """A single tool invocation requested by the model.

    pi origin: `AgentToolCall` (content block with type "toolCall").
    """

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """Result returned by a tool's `execute`.

    pi origin: `AgentToolResult`. `terminate` hints the loop to stop after this
    batch (see pi README "terminate: true").
    """

    content: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    is_error: bool = False
    terminate: bool = False


@dataclass
class Message:
    """A single transcript entry.

    pi origin: union of `user` / `assistant` / `toolResult` messages. Fields that
    only apply to one role are left at their defaults for the others.
    """

    role: Role
    content: str = ""
    timestamp: float = field(default_factory=time.time)

    # assistant-only
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: StopReason | None = None
    error_message: str | None = None

    # tool_result-only
    tool_call_id: str | None = None
    tool_name: str | None = None
    is_error: bool = False

    def has_tool_calls(self) -> bool:
        return self.role == "assistant" and len(self.tool_calls) > 0


@dataclass
class LlmContext:
    """What the ModelProvider is given for one request.

    pi origin: `Context` ({ systemPrompt, messages, tools }) built inside
    `streamAssistantResponse` after `convertToLlm`.
    """

    system_prompt: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]


def user_message(text: str) -> Message:
    return Message(role="user", content=text)
