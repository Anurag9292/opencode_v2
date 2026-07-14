from typing import Protocol

from ..types import Message


class Session(Protocol):
    """The public entrypoint; owns identity and wiring.

    A session owns: an id, its transcript (via the store), its permission
    ruleset, and the wired-together components (loop, tools, bus). The
    session itself contains almost no logic -- it is composition root, not
    behavior. In production harnesses this is also where sub-agents hang
    (a child session with a derived permission set).
    """

    @property
    def id(self) -> str: ...

    async def prompt(self, text: str) -> Message: ...
