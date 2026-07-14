"""InMemoryTraceRecorder — records every event in order, per session.

Wire it to the bus with ``bus.subscribe(recorder.record)``. ``export`` returns
the ordered trajectory for a session, the harness analogue of OpenHands'
trajectory export (docs Step 11).
"""

from __future__ import annotations

from ..types import Event


class InMemoryTraceRecorder:
    def __init__(self) -> None:
        self._events: list[Event] = []

    def record(self, event: Event) -> None:
        self._events.append(event)

    def export(self, session_id: str) -> list[Event]:
        return [e for e in self._events if e.session_id == session_id]

    def all(self) -> list[Event]:
        return list(self._events)
