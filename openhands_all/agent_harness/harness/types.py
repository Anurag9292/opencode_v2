"""Core value types for the harness.

These are deliberately plain dataclasses (no pydantic, no external deps) so the
harness is easy to read and runnable with a stock Python install. They model the
minimum vocabulary an agent turn needs:

    Message        - one entry in the conversation transcript
    ToolCall       - a request from the model to run a tool
    ToolResult     - the observation produced by running a tool
    ToolSpec       - the schema advertised to the model for one tool
    ModelResponse  - what a ModelProvider returns for one model call
    Event          - something worth broadcasting on the EventBus / trace

Mapping to the OpenHands architecture docs (see ../../docs/agent-turn-sequence.md):
    Message(role="user"/"assistant"/"tool")  ~ MessageEvent
    ToolCall                                  ~ ActionEvent
    ToolResult                                ~ ObservationEvent
    Event(kind="state")                       ~ ConversationStateUpdateEvent
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def now() -> float:
    return time.time()


@dataclass
class ToolCall:
    """A model's request to invoke a tool. Analogous to an ActionEvent."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """The result of running a tool. Analogous to an ObservationEvent."""

    call_id: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    """One transcript entry. The transcript is the single source of truth.

    - assistant messages may carry `tool_calls` (the model wants to act)
    - tool messages carry a single `tool_result` (the observation)
    """

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_result: ToolResult | None = None
    id: str = field(default_factory=lambda: new_id("msg"))
    created_at: float = field(default_factory=now)


class FinishReason(str, Enum):
    """Why a single model call stopped.

    TOOL_CALLS -> the model wants to run tools; the loop must continue.
    STOP       -> the model produced a final answer; the turn ends.
    LENGTH     -> truncated; treated as terminal by the reference loop.
    """

    TOOL_CALLS = "tool_calls"
    STOP = "stop"
    LENGTH = "length"


@dataclass
class ModelResponse:
    """The output of exactly one ModelProvider call."""

    message: Message
    finish_reason: FinishReason
    usage: dict[str, int] = field(default_factory=dict)


@dataclass
class ToolSpec:
    """Schema advertised to the model so it knows a tool exists.

    `parameters` is a JSON-schema-ish dict. `writes` marks tools whose effects
    are side-effecting (used by the PermissionPolicy to decide when to confirm).
    """

    name: str
    description: str
    parameters: dict[str, Any]
    writes: bool = False


class EventKind(str, Enum):
    """Categories broadcast on the EventBus and recorded by the TraceRecorder."""

    SESSION_CREATED = "session_created"
    USER_MESSAGE = "user_message"
    MODEL_REQUEST = "model_request"
    MODEL_RESPONSE = "model_response"
    TOOL_CALL = "tool_call"
    PERMISSION_CHECK = "permission_check"
    TOOL_RESULT = "tool_result"
    ITERATION = "iteration"
    TURN_COMPLETE = "turn_complete"
    ERROR = "error"


@dataclass
class Event:
    """A broadcastable, recordable fact about a turn.

    Mirrors the app_server model where the runtime emits a stream of typed
    events that get persisted and fanned out to callbacks.
    """

    kind: EventKind
    session_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: new_id("evt"))
    created_at: float = field(default_factory=now)
