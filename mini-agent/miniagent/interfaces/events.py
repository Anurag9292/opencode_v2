from typing import Callable, Protocol

from ..types import Event


class EventBus(Protocol):
    """Decouples the loop from everything that watches it.

    The loop only ever *publishes*; it never knows whether a terminal UI,
    a trace recorder, or a test assertion is listening. Subscribing with
    type "*" receives everything -- that is how the TraceRecorder attaches.

    Event types used by the reference implementation:
      session.created, message.created, message.part.delta,
      message.updated, tool.started, tool.finished,
      permission.asked, permission.replied, session.idle, session.error
    """

    def publish(self, event: Event) -> None: ...

    def subscribe(self, type: str, handler: Callable[[Event], None]) -> Callable[[], None]:
        """Returns an unsubscribe function."""
        ...
