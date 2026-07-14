"""AgentSession — a conversation handle bound to an AgentLoop.

Creating a session registers it with the store and emits SESSION_CREATED, the
harness analogue of OpenHands' conversation creation (docs Step 2). ``send``
delegates one full turn to the loop.
"""

from __future__ import annotations

from ..interfaces.events import EventBus
from ..interfaces.loop import AgentLoop
from ..interfaces.store import MessageStore
from ..types import Event, EventKind, Message, new_id


class AgentSession:
    def __init__(
        self,
        loop: AgentLoop,
        store: MessageStore,
        bus: EventBus,
        session_id: str | None = None,
    ) -> None:
        self._id = session_id or new_id("sess")
        self._loop = loop
        self._store = store
        self._bus = bus
        self._store.create_session(self._id)
        self._bus.publish(Event(kind=EventKind.SESSION_CREATED, session_id=self._id))

    @property
    def id(self) -> str:
        return self._id

    def send(self, user_text: str) -> Message:
        return self._loop.run(self._id, user_text)

    def history(self) -> list[Message]:
        return self._store.history(self._id)
