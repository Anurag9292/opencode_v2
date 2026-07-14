import fnmatch
from dataclasses import dataclass
from typing import Callable

from ..types import Decision, Event, PermissionDenied, PermissionRequest, Reply

from .events import InMemoryEventBus


@dataclass
class Rule:
    action: str      # matches PermissionRequest.action, e.g. "write", "bash"
    pattern: str     # wildcard over PermissionRequest.pattern
    decision: Decision


class RulePermissionPolicy:
    """Ordered wildcard rules; the LAST matching rule wins; default "ask".

    "ask" escalates to a human through the `asker` callback (installed by
    the Session -- in the CLI it is an input() prompt). A reply of "always"
    appends an allow rule so the session stops asking for that pattern.
    """

    def __init__(
        self,
        rules: list[Rule] | None = None,
        asker: Callable[[PermissionRequest], Reply] | None = None,
        bus: InMemoryEventBus | None = None,
    ) -> None:
        self.rules = rules or []
        self.asker = asker or (lambda request: "reject")
        self.bus = bus

    def check(self, request: PermissionRequest) -> None:
        decision = self._decide(request)
        if decision == "allow":
            return
        if decision == "deny":
            raise PermissionDenied(f"{request.action} on {request.pattern!r} is denied by policy")
        self._publish("permission.asked", request)
        self.reply(request, self.asker(request))

    def reply(self, request: PermissionRequest, reply: Reply) -> None:
        self._publish("permission.replied", request, reply=reply)
        if reply == "reject":
            raise PermissionDenied(f"user rejected {request.action} on {request.pattern!r}")
        if reply == "always":
            self.rules.append(Rule(request.action, request.pattern, "allow"))

    def _decide(self, request: PermissionRequest) -> Decision:
        decision: Decision = "ask"
        for rule in self.rules:
            if rule.action == request.action and fnmatch.fnmatch(request.pattern, rule.pattern):
                decision = rule.decision
        return decision

    def _publish(self, type: str, request: PermissionRequest, **extra: str) -> None:
        if not self.bus:
            return
        self.bus.publish(Event(type=type, data={
            "session_id": request.session_id,
            "tool": request.tool,
            "action": request.action,
            "pattern": request.pattern,
            **extra,
        }))
