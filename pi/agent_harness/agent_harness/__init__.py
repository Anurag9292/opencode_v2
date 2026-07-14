"""agent_harness: a minimal coding-agent harness in Python.

A from-scratch reimplementation of the essential pi agent loop, distilled from
pi/docs/agent-turn-sequence.md and pi/docs/core-module-map.md. It keeps the agent
logic and drops the production surface (steering, compaction, retries, extensions,
TUI, providers) so the core turn loop is easy to read.

Public interfaces (see each module for its pi origin):
  - ModelProvider      -> model_provider.py   (pi: streamFn / streamSimple)
  - AgentLoop          -> agent_loop.py        (pi: runLoop / streamAssistantResponse)
  - MessageStore       -> message_store.py     (pi: SessionManager)
  - ContextBuilder     -> context_builder.py   (pi: buildSystemPrompt + convertToLlm)
  - Tool / ToolRegistry-> tools.py             (pi: AgentTool + AgentSession._toolRegistry)
  - PermissionPolicy   -> permissions.py       (pi: beforeToolCall / tool_call hook)
  - EventBus           -> events.py            (pi: Agent.subscribe / processEvents)
  - Session            -> session.py           (pi: AgentSession + createAgentSession)
  - TraceRecorder      -> trace.py             (pi: observability event sink)
"""

from __future__ import annotations

from .agent_loop import AgentLoop, AgentLoopConfig
from .context_builder import ContextBuilder
from .events import Event, EventBus
from .message_store import InMemoryMessageStore, JsonlMessageStore, MessageStore
from .model_provider import (
    ModelProvider,
    OpenAIChatProvider,
    PlannedResponse,
    ScriptedModelProvider,
    StreamEvent,
    tool_call,
)
from .permissions import AllowAll, ConfirmCallback, DenyList, PermissionDecision, PermissionPolicy
from .session import Session
from .tools import (
    BashTool,
    ListDirTool,
    ReadFileTool,
    Tool,
    ToolRegistry,
    WriteFileTool,
    default_tools,
    validate_arguments,
)
from .trace import TraceRecorder
from .types import LlmContext, Message, ToolCall, ToolResult, user_message

__all__ = [
    "AgentLoop",
    "AgentLoopConfig",
    "ContextBuilder",
    "Event",
    "EventBus",
    "InMemoryMessageStore",
    "JsonlMessageStore",
    "MessageStore",
    "ModelProvider",
    "OpenAIChatProvider",
    "PlannedResponse",
    "ScriptedModelProvider",
    "StreamEvent",
    "tool_call",
    "AllowAll",
    "ConfirmCallback",
    "DenyList",
    "PermissionDecision",
    "PermissionPolicy",
    "Session",
    "BashTool",
    "ListDirTool",
    "ReadFileTool",
    "Tool",
    "ToolRegistry",
    "WriteFileTool",
    "default_tools",
    "validate_arguments",
    "TraceRecorder",
    "LlmContext",
    "Message",
    "ToolCall",
    "ToolResult",
    "user_message",
]
