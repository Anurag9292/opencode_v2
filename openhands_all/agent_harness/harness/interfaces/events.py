"""EventBus — in-process fan-out of turn events.

This is the harness analogue of OpenHands' event webhook + callback system
(docs Steps 7-9): the runtime emits typed events; subscribers persist them,
update UI, generate titles, etc. Keeping it in-process (rather than an HTTP
webhook) is the deliberate simplification for an educational harness.

Contract:
- ``subscribe`` registers a callable invoked for every published event
- ``publish`` delivers synchronously to all subscribers
- a failing subscriber must not break publishing for the others (isolate errors)
"""

from __future__ import annotations

from typing import Callable, Protocol

from ..types import Event

Subscriber = Callable[[Event], None]


class EventBus(Protocol):
    def subscribe(self, subscriber: Subscriber) -> None: ...

    def publish(self, event: Event) -> None: ...
