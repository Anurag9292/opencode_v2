"""SimpleEventBus — synchronous in-process fan-out.

Delivers each published event to every subscriber. A failing subscriber is
isolated (logged to stderr) so it cannot break delivery to the others — the same
resilience OpenHands' background callback runner provides (docs Step 9).
"""

from __future__ import annotations

import sys
import traceback

from ..interfaces.events import Subscriber
from ..types import Event


class SimpleEventBus:
    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []

    def subscribe(self, subscriber: Subscriber) -> None:
        self._subscribers.append(subscriber)

    def publish(self, event: Event) -> None:
        for subscriber in self._subscribers:
            try:
                subscriber(event)
            except Exception:  # isolate a bad subscriber
                print(
                    f"[eventbus] subscriber failed for {event.kind}:",
                    file=sys.stderr,
                )
                traceback.print_exc()
