from collections import defaultdict
from typing import Callable

from ..types import Event


class InMemoryEventBus:
    """Synchronous fan-out. Handler errors are isolated so one bad
    observer (e.g. a UI) can never kill the agent loop."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[Event], None]]] = defaultdict(list)

    def publish(self, event: Event) -> None:
        for handler in [*self._handlers[event.type], *self._handlers["*"]]:
            try:
                handler(event)
            except Exception:
                pass

    def subscribe(self, type: str, handler: Callable[[Event], None]) -> Callable[[], None]:
        self._handlers[type].append(handler)
        return lambda: self._handlers[type].remove(handler)
