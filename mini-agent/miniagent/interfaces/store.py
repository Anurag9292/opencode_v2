from typing import Protocol

from ..types import Message


class MessageStore(Protocol):
    """Durable, ordered transcript per session.

    The store is the single source of truth for history: the loop re-reads
    it at the start of every turn instead of keeping messages in local
    variables. That discipline is what makes resume-after-crash and
    multi-observer UIs possible later.

    save() is an upsert keyed by message.id -- the loop saves the same
    assistant message repeatedly as parts stream in.
    """

    def save(self, message: Message) -> None: ...

    def history(self, session_id: str) -> list[Message]: ...
