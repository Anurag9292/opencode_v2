"""Core data types shared by every component of the harness.

These are deliberately plain dataclasses: the educational point is that a
coding agent is mostly a state machine over a few simple records.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Literal
import time
import uuid


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------- messages

@dataclass
class TextPart:
    """A chunk of assistant or user text."""
    text: str
    type: Literal["text"] = "text"


ToolStatus = Literal["pending", "running", "completed", "error"]


@dataclass
class ToolCallPart:
    """One tool invocation requested by the model.

    The part is a small state machine: pending -> running -> completed|error.
    The tool's output is stored on the part itself, so the full transcript of
    a turn lives inside the assistant message that caused it.
    """
    call_id: str
    tool: str
    args: dict[str, Any]
    status: ToolStatus = "pending"
    output: str = ""
    error: str = ""
    title: str = ""
    type: Literal["tool"] = "tool"


Part = TextPart | ToolCallPart

Role = Literal["user", "assistant"]

FinishReason = Literal["stop", "tool_calls", "length", "error", "unknown"]


@dataclass
class Message:
    id: str
    session_id: str
    role: Role
    parts: list[Part] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    finish_reason: FinishReason | None = None
    usage: dict[str, int] = field(default_factory=dict)

    def text(self) -> str:
        return "".join(p.text for p in self.parts if isinstance(p, TextPart))

    def tool_calls(self) -> list[ToolCallPart]:
        return [p for p in self.parts if isinstance(p, ToolCallPart)]


# ------------------------------------------------------------ model stream

@dataclass
class TextDelta:
    """Incremental assistant text."""
    text: str


@dataclass
class ToolCallRequest:
    """The model asked to run a tool."""
    call_id: str
    tool: str
    args: dict[str, Any]


@dataclass
class Finish:
    """The model finished its turn."""
    reason: FinishReason
    usage: dict[str, int] = field(default_factory=dict)


ModelEvent = TextDelta | ToolCallRequest | Finish


@dataclass
class ModelContext:
    """Everything a provider needs for one model call."""
    system: str
    messages: list[Message]


# ------------------------------------------------------------------ tools

@dataclass
class ToolSpec:
    """Provider-facing tool description (JSON-schema parameters)."""
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolResult:
    output: str
    title: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolContext:
    """Handed to Tool.execute.

    ask() is the permission gate: tools describe the action they are about to
    take and raise PermissionDenied if the policy (or the human) says no.
    """
    session_id: str
    workdir: str
    ask: Callable[["PermissionRequest"], None]


# ------------------------------------------------------------- permissions

@dataclass
class PermissionRequest:
    session_id: str
    tool: str
    action: str      # e.g. "write", "bash"
    pattern: str     # e.g. a file path or shell command


Decision = Literal["allow", "ask", "deny"]

Reply = Literal["once", "always", "reject"]


class PermissionDenied(Exception):
    pass


# ------------------------------------------------------------------ events

@dataclass
class Event:
    type: str
    data: dict[str, Any]
    time: float = field(default_factory=time.time)
