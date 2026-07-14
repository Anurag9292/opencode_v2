"""ModelProvider — the boundary to an LLM.

In OpenHands the actual provider call happens inside the agent-server via the
SDK's ``LLM`` (see ../../docs/agent-turn-sequence.md, Step 5/6, marked
[EXTERNAL]). Here we make it a first-class, swappable interface so the loop can
run against a fake, a scripted, or a real provider without changing.

Contract:
- exactly one ``complete()`` per model call (one turn iteration)
- given the full context (system + transcript) and the advertised tool specs,
  return one ModelResponse
- the provider decides finish_reason: TOOL_CALLS means "run these tools and
  call me again"; STOP means "this is my final answer".
"""

from __future__ import annotations

from typing import Protocol

from ..types import Message, ModelResponse, ToolSpec


class ModelProvider(Protocol):
    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> ModelResponse: ...
