"""PermissionPolicy interface + implementations.

pi origin: the `beforeToolCall` hook wired in `AgentSession._installAgentToolHooks`
(packages/coding-agent/src/core/agent-session.ts), which forwards to the extension
`tool_call` event and can `{ block: true, reason }`.

Design note (verified against pi): pi ships **no built-in permission popups**. The
only gate is this hook. We make the gate a first-class interface here so the
permission decision is explicit and testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from .types import ToolCall


@dataclass
class PermissionDecision:
    allow: bool
    reason: str = ""


@runtime_checkable
class PermissionPolicy(Protocol):
    def check(self, tool_call: ToolCall) -> PermissionDecision: ...


class AllowAll:
    """Default policy: run everything (matches pi with no tool_call handler)."""

    def check(self, tool_call: ToolCall) -> PermissionDecision:
        return PermissionDecision(allow=True)


@dataclass
class DenyList:
    """Block a fixed set of tool names."""

    blocked: frozenset[str]

    def check(self, tool_call: ToolCall) -> PermissionDecision:
        if tool_call.name in self.blocked:
            return PermissionDecision(allow=False, reason=f"Tool '{tool_call.name}' is disabled by policy")
        return PermissionDecision(allow=True)


@dataclass
class ConfirmCallback:
    """Delegate the decision to a callback (e.g. an interactive confirm prompt)."""

    confirm: Callable[[ToolCall], bool]

    def check(self, tool_call: ToolCall) -> PermissionDecision:
        if self.confirm(tool_call):
            return PermissionDecision(allow=True)
        return PermissionDecision(allow=False, reason="User declined execution")
