import json
import os
import urllib.request
from typing import AsyncIterator

from ..types import Finish, ModelContext, ModelEvent, TextDelta, ToolCallRequest, ToolSpec
from ..types import Message, TextPart, ToolCallPart


class AnthropicProvider:
    """Minimal Anthropic Messages API adapter (stdlib only, no SDK).

    Educational simplification: the request is non-streaming; we make one
    blocking HTTP call per turn and then emit the normalized events the
    AgentLoop expects. Swapping this for true SSE streaming changes ONLY
    this file -- the loop already consumes an event stream. That is the
    payoff of the ModelProvider seam.
    """

    def __init__(self, model: str = "claude-haiku-4-5", api_key: str | None = None) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set")

    async def stream(
        self, context: ModelContext, tools: list[ToolSpec]
    ) -> AsyncIterator[ModelEvent]:
        body = {
            "model": self.model,
            "max_tokens": 4096,
            "system": context.system,
            "messages": self._encode_history(context.messages),
            "tools": [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ],
        }
        request = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(body).encode(),
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        with urllib.request.urlopen(request) as response:
            data = json.loads(response.read())

        for block in data.get("content", []):
            if block["type"] == "text":
                yield TextDelta(text=block["text"])
            if block["type"] == "tool_use":
                yield ToolCallRequest(call_id=block["id"], tool=block["name"], args=block["input"])

        reason = {"end_turn": "stop", "tool_use": "tool_calls", "max_tokens": "length"}.get(
            data.get("stop_reason", ""), "unknown"
        )
        usage = data.get("usage", {})
        yield Finish(reason=reason, usage={
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        })

    def _encode_history(self, messages: list[Message]) -> list[dict]:
        """Flatten our Message/Part model into Anthropic's wire format.

        Assistant tool calls become tool_use blocks; their stored outputs
        become a synthetic user message of tool_result blocks -- this is
        how completed tool work re-enters the conversation.
        """
        encoded: list[dict] = []
        for message in messages:
            content: list[dict] = []
            results: list[dict] = []
            for part in message.parts:
                if isinstance(part, TextPart) and part.text:
                    content.append({"type": "text", "text": part.text})
                if isinstance(part, ToolCallPart):
                    content.append({
                        "type": "tool_use",
                        "id": part.call_id,
                        "name": part.tool,
                        "input": part.args,
                    })
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": part.call_id,
                        "content": part.output if part.status == "completed" else f"ERROR: {part.error}",
                        "is_error": part.status == "error",
                    })
            if content:
                encoded.append({"role": message.role, "content": content})
            if results:
                encoded.append({"role": "user", "content": results})
        return encoded
