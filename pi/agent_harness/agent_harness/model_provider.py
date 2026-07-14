"""ModelProvider interface + implementations.

pi origin: the `streamFn` wrapper built in `createAgentSession` (packages/coding-agent/src/core/sdk.ts)
which calls `streamSimple` (packages/ai/src/compat.ts). A provider turns an
`LlmContext` into a stream of low-level assistant events that the AgentLoop
assembles into an `AssistantMessage` (mirrors `streamAssistantResponse`).

The event union mirrors pi's `AssistantMessageEvent` (packages/ai/src/types.ts),
trimmed to: start, text_delta, toolcall, done, error.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal, Protocol, runtime_checkable

from .types import LlmContext, StopReason, ToolCall

StreamEventType = Literal["start", "text_delta", "toolcall", "done", "error"]


@dataclass
class StreamEvent:
    type: StreamEventType
    # text_delta
    delta: str = ""
    # toolcall
    tool_call: ToolCall | None = None
    # done
    stop_reason: StopReason | None = None
    # error
    error: str = ""


@runtime_checkable
class ModelProvider(Protocol):
    """Streams assistant events for a single model request.

    pi origin: `StreamFn` (packages/agent/src/types.ts) / `streamSimple`.
    """

    name: str

    def stream(self, context: LlmContext) -> Iterator[StreamEvent]: ...


# ---------------------------------------------------------------------------
# Scripted mock provider (offline, deterministic) - used by the demo & tests.
# ---------------------------------------------------------------------------


@dataclass
class PlannedResponse:
    """One scripted assistant turn: either text or a set of tool calls."""

    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class ScriptedModelProvider:
    """Yields a fixed sequence of assistant turns, one per `stream()` call.

    This is the offline stand-in for a real LLM. It lets us exercise the full
    agent loop (tool call -> tool result -> final answer) with zero network.
    Once the plan is exhausted it emits a benign final message so the loop
    always terminates.
    """

    name = "scripted-mock"

    def __init__(self, plan: list[PlannedResponse]) -> None:
        self._plan = list(plan)
        self._index = 0

    def stream(self, context: LlmContext) -> Iterator[StreamEvent]:
        if self._index < len(self._plan):
            step = self._plan[self._index]
        else:
            step = PlannedResponse(text="Done.")
        self._index += 1

        yield StreamEvent(type="start")

        if step.tool_calls:
            for call in step.tool_calls:
                yield StreamEvent(type="toolcall", tool_call=call)
            yield StreamEvent(type="done", stop_reason="tool_use")
            return

        # Stream the text in a few chunks to exercise message_update handling.
        text = step.text or ""
        for chunk in _chunk(text, size=12):
            yield StreamEvent(type="text_delta", delta=chunk)
        yield StreamEvent(type="done", stop_reason="end")


def _chunk(text: str, size: int) -> Iterator[str]:
    for i in range(0, len(text), size):
        yield text[i : i + size]


def tool_call(name: str, arguments: dict[str, Any]) -> ToolCall:
    return ToolCall(id=f"call_{uuid.uuid4().hex[:8]}", name=name, arguments=arguments)


# ---------------------------------------------------------------------------
# Optional OpenAI-compatible provider (real network, stdlib only).
# Enabled only when OPENAI_API_KEY is set. Non-streaming under the hood; the
# single response is re-emitted as stream events so the loop is unchanged.
# ---------------------------------------------------------------------------


class OpenAIChatProvider:
    """Minimal OpenAI-compatible chat.completions provider using urllib.

    pi origin: analogous to `packages/ai/src/api/openai-completions.ts`, reduced
    to a single non-streaming request. Tool calling uses the OpenAI `tools` schema.
    """

    name = "openai-chat"

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.base_url = base_url.rstrip("/")

    def stream(self, context: LlmContext) -> Iterator[StreamEvent]:
        if not self.api_key:
            yield StreamEvent(type="start")
            yield StreamEvent(type="error", error="OPENAI_API_KEY not set")
            return

        import urllib.error
        import urllib.request

        messages = [{"role": "system", "content": context.system_prompt}, *context.messages]
        body = {"model": self.model, "messages": messages}
        if context.tools:
            body["tools"] = [
                {"type": "function", "function": {"name": t["name"], "description": t.get("description", ""), "parameters": t["parameters"]}}
                for t in context.tools
            ]

        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )

        yield StreamEvent(type="start")
        try:
            with urllib.request.urlopen(request, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - network path
            yield StreamEvent(type="error", error=f"HTTP {exc.code}: {exc.read().decode('utf-8', 'ignore')}")
            return
        except Exception as exc:  # pragma: no cover - network path
            yield StreamEvent(type="error", error=str(exc))
            return

        choice = data["choices"][0]
        msg = choice["message"]
        raw_tool_calls = msg.get("tool_calls") or []
        if raw_tool_calls:
            for tc in raw_tool_calls:
                fn = tc["function"]
                arguments = json.loads(fn.get("arguments") or "{}")
                yield StreamEvent(type="toolcall", tool_call=ToolCall(id=tc["id"], name=fn["name"], arguments=arguments))
            yield StreamEvent(type="done", stop_reason="tool_use")
            return

        for chunk in _chunk(msg.get("content") or "", size=40):
            yield StreamEvent(type="text_delta", delta=chunk)
        finish = choice.get("finish_reason")
        yield StreamEvent(type="done", stop_reason="length" if finish == "length" else "end")
