from typing import Protocol

from ..types import Event


class TraceRecorder(Protocol):
    """Durable, append-only record of everything that happened.

    Distinct from the MessageStore: the store holds the *transcript* (what
    the model sees next turn), the trace holds the *history of the run*
    (every event, in order, with timestamps) for debugging, replay, and
    evals. The reference implementation is just an event-bus subscriber
    writing JSONL.
    """

    def record(self, event: Event) -> None: ...

    def read(self, session_id: str) -> list[Event]: ...
