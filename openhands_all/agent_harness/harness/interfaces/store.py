"""MessageStore — durable transcript, the single source of truth.

Key teaching point from the OpenHands docs: the transcript (event history) is
authoritative. The loop re-reads history from the store on every iteration
rather than trusting in-memory state, so a restart or a second worker sees a
consistent view.

Contract:
- ``append`` adds one message and returns it (with ids/timestamps populated)
- ``history`` returns the ordered transcript for a session
- ``create_session`` / ``sessions`` manage session existence
Implementations may be in-memory (tests) or file-backed (persistence).
"""

from __future__ import annotations

from typing import Protocol

from ..types import Message


class MessageStore(Protocol):
    def create_session(self, session_id: str) -> None: ...

    def sessions(self) -> list[str]: ...

    def append(self, session_id: str, message: Message) -> Message: ...

    def history(self, session_id: str) -> list[Message]: ...
