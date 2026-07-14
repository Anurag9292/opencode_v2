"""The ten seams of the harness.

Every interface is a typing.Protocol so implementations need no inheritance;
any object with the right methods qualifies. Each one corresponds to a real
seam in production coding agents (OpenCode, Claude Code, etc.):

    ModelProvider     talk to an LLM, normalize its stream
    MessageStore      persist the transcript
    ContextBuilder    turn history + environment into a model request
    Tool              one capability the model may invoke
    ToolRegistry      assemble/filter the toolset for a session
    PermissionPolicy  gate side effects (allow / ask / deny)
    EventBus          decouple the loop from every observer (UI, trace, ...)
    TraceRecorder     durable record of everything, for debugging & evals
    AgentLoop         the turn loop: model -> tools -> model -> ... -> stop
    Session           owns identity + wiring; the public entrypoint
"""

from .model import ModelProvider
from .store import MessageStore
from .context import ContextBuilder
from .tool import Tool, ToolRegistry
from .permission import PermissionPolicy
from .events import EventBus
from .trace import TraceRecorder
from .loop import AgentLoop
from .session import Session

__all__ = [
    "ModelProvider",
    "MessageStore",
    "ContextBuilder",
    "Tool",
    "ToolRegistry",
    "PermissionPolicy",
    "EventBus",
    "TraceRecorder",
    "AgentLoop",
    "Session",
]
