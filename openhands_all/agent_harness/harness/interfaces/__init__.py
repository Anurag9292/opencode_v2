"""Abstract interfaces (Protocols) for the harness.

Each interface names one responsibility from the OpenHands architecture docs.
Reference implementations live in ``harness.impl`` and ``harness.tools``.
"""

from .model import ModelProvider
from .loop import AgentLoop
from .store import MessageStore
from .context import ContextBuilder
from .tool import Tool, ToolRegistry
from .permission import Decision, PermissionPolicy
from .events import EventBus, Subscriber
from .session import Session
from .trace import TraceRecorder

__all__ = [
    "ModelProvider",
    "AgentLoop",
    "MessageStore",
    "ContextBuilder",
    "Tool",
    "ToolRegistry",
    "PermissionPolicy",
    "Decision",
    "EventBus",
    "Subscriber",
    "Session",
    "TraceRecorder",
]
