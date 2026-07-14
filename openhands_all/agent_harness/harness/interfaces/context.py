"""ContextBuilder — assembles the messages sent to the model.

This is the harness equivalent of OpenHands' system-prompt construction plus
"instruction loading" (skills/microagents/suffixes). See
../../docs/agent-turn-sequence.md Steps 3-4. In OpenHands the final system
string is rendered externally from a Jinja template; here we build it in-process
so it is fully inspectable.

Responsibilities:
- render the system prompt (persona + tool-use rules + loaded instructions)
- optionally prepend/append instruction fragments ("skills")
- apply a context window budget (truncate/condense old turns)
- return the exact ``list[Message]`` handed to ``ModelProvider.complete``

Contract: pure and deterministic given (system inputs, history). No I/O in the
hot path beyond reading already-loaded instructions.
"""

from __future__ import annotations

from typing import Protocol

from ..types import Message


class ContextBuilder(Protocol):
    def build(self, session_id: str, history: list[Message]) -> list[Message]: ...
