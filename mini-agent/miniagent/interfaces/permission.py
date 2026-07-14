from typing import Protocol

from ..types import PermissionRequest, Reply


class PermissionPolicy(Protocol):
    """Gates side effects before tools perform them.

    check() resolves a request to one of:
      allow  -> proceed silently
      deny   -> raise PermissionDenied (the model sees the refusal as a
                tool error and can adapt)
      ask    -> escalate to a human via the asker installed by the Session

    reply() records the human's answer; "always" should widen the ruleset
    so the same request is auto-allowed for the rest of the session.
    """

    def check(self, request: PermissionRequest) -> None: ...

    def reply(self, request: PermissionRequest, reply: Reply) -> None: ...
