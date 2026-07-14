"""Session — one conversation's identity and its wiring.

In OpenHands a conversation is created, bound to a runtime, and then driven turn
by turn (docs Step 2). Here a Session is the small object that owns a
``session_id`` and delegates ``send()`` to the AgentLoop. It is the public
surface a caller (CLI, server, test) uses.

Contract:
- ``id`` is stable for the life of the conversation
- ``send(user_text)`` runs one full turn (may involve many model iterations) and
  returns the final assistant Message
"""

from __future__ import annotations

from typing import Protocol

from ..types import Message


class Session(Protocol):
    @property
    def id(self) -> str: ...

    def send(self, user_text: str) -> Message: ...
