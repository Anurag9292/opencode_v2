"""Harness — the composition root that wires every component together.

This is the one place that knows how the pieces fit. It mirrors what
OpenHands' ``LiveStatusAppConversationService`` does when it assembles an agent
(docs Step 4): pick a model, register tools, choose a permission policy, build
context, and start driving turns — minus the sandbox/HTTP indirection.

``build_default_harness`` returns a fully-working, dependency-free harness
(EchoModelProvider + builtin tools + in-memory store/trace) so you can::

    from harness.impl import build_default_harness
    h = build_default_harness()
    session = h.new_session()
    print(session.send("read README.md").content)
"""

from __future__ import annotations

from pathlib import Path

from ..interfaces.context import ContextBuilder
from ..interfaces.events import EventBus
from ..interfaces.model import ModelProvider
from ..interfaces.permission import PermissionPolicy
from ..interfaces.store import MessageStore
from ..interfaces.tool import Tool, ToolRegistry
from ..interfaces.trace import TraceRecorder
from .context import SystemPromptContextBuilder
from .events import SimpleEventBus
from .loop import ReactAgentLoop
from .permission import ConfirmRisky
from .providers import EchoModelProvider
from .registry import DictToolRegistry
from .session import AgentSession
from .store import InMemoryMessageStore
from .trace import InMemoryTraceRecorder


class Harness:
    def __init__(
        self,
        model: ModelProvider,
        store: MessageStore,
        registry: ToolRegistry,
        context_builder: ContextBuilder,
        permissions: PermissionPolicy,
        bus: EventBus,
        trace: TraceRecorder,
        max_iterations: int = 20,
    ) -> None:
        self.model = model
        self.store = store
        self.registry = registry
        self.context_builder = context_builder
        self.permissions = permissions
        self.bus = bus
        self.trace = trace
        # Trace everything the loop emits.
        self.bus.subscribe(self.trace.record)
        self.loop = ReactAgentLoop(
            model=model,
            store=store,
            context_builder=context_builder,
            registry=registry,
            permissions=permissions,
            bus=bus,
            max_iterations=max_iterations,
        )

    def new_session(self, session_id: str | None = None) -> AgentSession:
        return AgentSession(self.loop, self.store, self.bus, session_id=session_id)


def build_default_harness(
    *,
    model: ModelProvider | None = None,
    tools: list[Tool] | None = None,
    permissions: PermissionPolicy | None = None,
    workspace: str | Path = ".",
    max_iterations: int = 20,
) -> Harness:
    """Assemble a runnable harness with sensible educational defaults."""
    from ..tools.builtin import default_tools

    registry = DictToolRegistry()
    for tool in tools if tools is not None else default_tools(workspace):
        registry.register(tool)

    return Harness(
        model=model or EchoModelProvider(),
        store=InMemoryMessageStore(),
        registry=registry,
        context_builder=SystemPromptContextBuilder(registry),
        permissions=permissions or ConfirmRisky(),  # read-only allowed, writes denied by default
        bus=SimpleEventBus(),
        trace=InMemoryTraceRecorder(),
        max_iterations=max_iterations,
    )
