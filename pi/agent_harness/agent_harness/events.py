"""Event types and the EventBus.

pi origin:
  - Event vocabulary mirrors `AgentEvent` (packages/agent/src/types.ts): agent_start,
    turn_start, message_start/update/end, tool_execution_start/update/end, turn_end,
    agent_end.
  - `EventBus` mirrors `Agent.subscribe` / `Agent.processEvents` (packages/agent/src/agent.ts)
    and `AgentSession._emit` (packages/coding-agent/src/core/agent-session.ts).

Subtracted from pi: pi awaits async listeners in registration order and folds
`agent_end` settlement into idle tracking. Here listeners are synchronous and
called in registration order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

EventType = str  # one of the constants below

# Lifecycle
AGENT_START = "agent_start"
AGENT_END = "agent_end"
TURN_START = "turn_start"
TURN_END = "turn_end"

# Messages
MESSAGE_START = "message_start"
MESSAGE_UPDATE = "message_update"
MESSAGE_END = "message_end"

# Tools
TOOL_EXECUTION_START = "tool_execution_start"
TOOL_EXECUTION_UPDATE = "tool_execution_update"
TOOL_EXECUTION_END = "tool_execution_end"


@dataclass
class Event:
    """A lifecycle event. `payload` carries type-specific fields.

    Using one dataclass with a `type` string (instead of a class per event) keeps
    the bus tiny; the payload keys match the pi event field names.
    """

    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)

    def __getattr__(self, item: str) -> Any:  # convenience: event.message, event.tool_name
        try:
            return self.payload[item]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(item) from exc


Listener = Callable[[Event], None]


class EventBus:
    """Synchronous fan-out to registered listeners, in registration order."""

    def __init__(self) -> None:
        self._listeners: list[Listener] = []

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def emit(self, event: Event) -> None:
        # Iterate over a copy so listeners may unsubscribe during dispatch.
        for listener in list(self._listeners):
            listener(event)
