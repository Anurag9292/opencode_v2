"""PermissionPolicy — the confirmation / safety gate before a tool runs.

Maps to OpenHands' confirmation policy + security analyzer (docs Step 6):
``NeverConfirm`` / ``AlwaysConfirm`` / ``ConfirmRisky``. The policy sits between
tool-call *detection* and tool *execution*: the loop asks the policy for each
call and only executes when the decision is ALLOW.

Contract: ``check`` is side-effect free (it decides; it does not run the tool).
An interactive implementation may block on user input inside ``check``; a
headless one returns immediately.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from ..types import ToolCall, ToolSpec


class Decision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


class PermissionPolicy(Protocol):
    def check(self, call: ToolCall, spec: ToolSpec | None) -> Decision: ...
