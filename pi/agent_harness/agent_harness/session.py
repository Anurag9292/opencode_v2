"""Session: the orchestrator that wires everything together.

pi origin: `AgentSession` (packages/coding-agent/src/core/agent-session.ts) plus the
`createAgentSession` factory (packages/coding-agent/src/core/sdk.ts).

Key mirrored behavior:
  - Persistence is a side effect of the event stream: a subscriber persists each
    message on `message_end` (pi's `_handleAgentEvent`).
  - The Session owns the transcript (`history`) and hands a snapshot to the loop.
  - `prompt(text)` builds a user message and drives one full agent run.
"""

from __future__ import annotations

from dataclasses import dataclass

from .agent_loop import AgentLoop, AgentLoopConfig
from .context_builder import ContextBuilder
from .events import MESSAGE_END, Event, EventBus
from .message_store import InMemoryMessageStore, MessageStore
from .model_provider import ModelProvider
from .permissions import AllowAll, PermissionPolicy
from .tools import ToolRegistry, default_tools
from .types import Message, user_message


@dataclass
class Session:
    model: ModelProvider
    registry: ToolRegistry
    store: MessageStore
    context_builder: ContextBuilder
    bus: EventBus
    permission: PermissionPolicy
    loop: AgentLoop
    history: list[Message]

    @classmethod
    def create(
        cls,
        model: ModelProvider,
        *,
        cwd: str = ".",
        tools: list | None = None,
        store: MessageStore | None = None,
        permission: PermissionPolicy | None = None,
        context_builder: ContextBuilder | None = None,
        config: AgentLoopConfig | None = None,
    ) -> "Session":
        bus = EventBus()
        registry = ToolRegistry(tools if tools is not None else default_tools(cwd))
        store = store or InMemoryMessageStore()
        permission = permission or AllowAll()
        context_builder = context_builder or ContextBuilder(cwd=cwd)
        loop = AgentLoop(
            model=model,
            context_builder=context_builder,
            registry=registry,
            bus=bus,
            permission=permission,
            config=config,
        )
        history: list[Message] = list(store.get_messages())  # resume prior transcript if any

        session = cls(
            model=model,
            registry=registry,
            store=store,
            context_builder=context_builder,
            bus=bus,
            permission=permission,
            loop=loop,
            history=history,
        )
        # Persist every finalized message, exactly like pi's _handleAgentEvent.
        bus.subscribe(session._persist_on_message_end)
        return session

    def subscribe(self, listener):
        return self.bus.subscribe(listener)

    def prompt(self, text: str) -> list[Message]:
        return self.loop.run([user_message(text)], self.history)

    # -- internal ----------------------------------------------------------

    def _persist_on_message_end(self, event: Event) -> None:
        if event.type != MESSAGE_END:
            return
        message = event.payload["message"]
        if message.role in ("user", "assistant", "tool_result"):
            self.store.append(message)
