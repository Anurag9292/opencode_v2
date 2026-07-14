from typing import Protocol

from ..types import Message, ModelContext


class ContextBuilder(Protocol):
    """Turns raw history into what the model actually sees.

    Everything about "prompt engineering the harness" concentrates here:
    the system prompt, environment info (cwd, platform, date), project
    instructions (AGENTS.md), and eventually history truncation or
    summarization. Keeping it a pure function of (session_id, history)
    makes context assembly testable in isolation.
    """

    def build(self, session_id: str, history: list[Message]) -> ModelContext: ...
