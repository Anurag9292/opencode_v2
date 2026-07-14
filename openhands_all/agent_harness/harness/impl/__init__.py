"""Reference implementations of the harness interfaces."""

from .store import InMemoryMessageStore, FileMessageStore
from .context import SystemPromptContextBuilder
from .registry import DictToolRegistry
from .permission import NeverConfirm, AlwaysConfirm, ConfirmRisky, CallbackConfirm
from .events import SimpleEventBus
from .trace import InMemoryTraceRecorder
from .providers import ScriptedModelProvider, EchoModelProvider
from .loop import ReactAgentLoop
from .session import AgentSession
from .harness import Harness, build_default_harness

__all__ = [
    "InMemoryMessageStore",
    "FileMessageStore",
    "SystemPromptContextBuilder",
    "DictToolRegistry",
    "NeverConfirm",
    "AlwaysConfirm",
    "ConfirmRisky",
    "CallbackConfirm",
    "SimpleEventBus",
    "InMemoryTraceRecorder",
    "ScriptedModelProvider",
    "EchoModelProvider",
    "ReactAgentLoop",
    "AgentSession",
    "Harness",
    "build_default_harness",
]
