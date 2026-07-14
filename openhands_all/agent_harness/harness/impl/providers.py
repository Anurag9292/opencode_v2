"""ModelProvider implementations that need no network or API key.

- ScriptedModelProvider: replays a fixed list of ModelResponses. This makes the
  loop deterministic and testable, and is the clearest way to *demonstrate* the
  turn shape (assistant -> tool_call -> observation -> assistant -> stop).

- EchoModelProvider: a tiny heuristic "model" that reacts to the latest message.
  It shows how a provider inspects context and decides to call a tool vs finish,
  without any real intelligence — enough to run the demo end to end.

A real provider (OpenAI/Anthropic/etc.) implements the same ``complete`` method:
serialize ``messages`` + ``tools`` into the wire format, call the API, and parse
the response back into a ModelResponse. That boundary is intentionally the only
thing you swap to go from educational to real.
"""

from __future__ import annotations

from ..types import (
    FinishReason,
    Message,
    ModelResponse,
    ToolCall,
    ToolSpec,
    new_id,
)


class ScriptedModelProvider:
    """Replays pre-baked responses in order. Raises if it runs out."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = list(responses)
        self._i = 0

    def complete(
        self, messages: list[Message], tools: list[ToolSpec]
    ) -> ModelResponse:
        if self._i >= len(self._responses):
            raise RuntimeError("ScriptedModelProvider ran out of responses")
        response = self._responses[self._i]
        self._i += 1
        return response


class EchoModelProvider:
    """A rule-based stand-in model.

    Behavior (enough to exercise every branch of the loop):
    - if the user text mentions "read <path>", call the ``read_file`` tool once
    - after seeing a tool observation, produce a final answer and STOP
    - otherwise, echo the user text back as a final answer
    """

    def complete(
        self, messages: list[Message], tools: list[ToolSpec]
    ) -> ModelResponse:
        last = messages[-1] if messages else None
        tool_names = {t.name for t in tools}

        # If the previous message was a tool observation, wrap up.
        if last is not None and last.role == "tool" and last.tool_result:
            answer = f"Done. Observation was:\n{last.tool_result.content}"
            return ModelResponse(
                Message(role="assistant", content=answer), FinishReason.STOP
            )

        user_text = _latest_user_text(messages)
        if user_text and "read " in user_text and "read_file" in tool_names:
            path = user_text.split("read ", 1)[1].strip().split()[0]
            call = ToolCall(id=new_id("call"), name="read_file", arguments={"path": path})
            return ModelResponse(
                Message(role="assistant", content="I'll read that file.", tool_calls=[call]),
                FinishReason.TOOL_CALLS,
            )

        return ModelResponse(
            Message(role="assistant", content=f"You said: {user_text or ''}"),
            FinishReason.STOP,
        )


def _latest_user_text(messages: list[Message]) -> str | None:
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return None
