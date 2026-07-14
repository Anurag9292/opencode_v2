"""TraceRecorder — a durable, ordered record of everything that happened.

Where the MessageStore keeps the *transcript* (what the model sees), the
TraceRecorder keeps the *trajectory* (every event: requests, tool calls,
permission decisions, errors). This mirrors OpenHands' event persistence +
trajectory export (docs Steps 8, 11) and is what you replay to debug a run.

A TraceRecorder is typically also an EventBus subscriber, so wiring it up is a
one-liner: ``bus.subscribe(trace.record)``.

Contract:
- ``record(event)`` appends one event durably/observably
- ``export(session_id)`` returns the ordered events for a session
"""

from __future__ import annotations

from typing import Protocol

from ..types import Event


class TraceRecorder(Protocol):
    def record(self, event: Event) -> None: ...

    def export(self, session_id: str) -> list[Event]: ...
