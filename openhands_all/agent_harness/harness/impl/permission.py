"""PermissionPolicy implementations.

These mirror OpenHands' confirmation policies (docs Step 6):

    NeverConfirm   - allow everything (headless / trusted)
    AlwaysConfirm  - confirm every tool call
    ConfirmRisky   - confirm only tools whose spec.writes is True
    CallbackConfirm- delegate the yes/no decision to a supplied callable
                     (e.g. an interactive CLI prompt)
"""

from __future__ import annotations

from typing import Callable

from ..interfaces.permission import Decision
from ..types import ToolCall, ToolSpec


class NeverConfirm:
    def check(self, call: ToolCall, spec: ToolSpec | None) -> Decision:
        return Decision.ALLOW


class AlwaysConfirm:
    """Denies by default; intended to be subclassed or used with a UI. The
    reference headless behavior is to deny, forcing an explicit policy choice.
    """

    def check(self, call: ToolCall, spec: ToolSpec | None) -> Decision:
        return Decision.DENY


class ConfirmRisky:
    """Allow read-only tools; deny (or defer) side-effecting ones.

    ``on_risky`` lets a caller plug in a real confirmation prompt. If omitted,
    risky calls are denied so the default is safe.
    """

    def __init__(
        self, on_risky: Callable[[ToolCall, ToolSpec | None], bool] | None = None
    ) -> None:
        self.on_risky = on_risky

    def check(self, call: ToolCall, spec: ToolSpec | None) -> Decision:
        if spec is not None and not spec.writes:
            return Decision.ALLOW
        if self.on_risky is None:
            return Decision.DENY
        return Decision.ALLOW if self.on_risky(call, spec) else Decision.DENY


class CallbackConfirm:
    """Delegate every decision to a callable returning True (allow)/False (deny)."""

    def __init__(self, decide: Callable[[ToolCall, ToolSpec | None], bool]) -> None:
        self.decide = decide

    def check(self, call: ToolCall, spec: ToolSpec | None) -> Decision:
        return Decision.ALLOW if self.decide(call, spec) else Decision.DENY
