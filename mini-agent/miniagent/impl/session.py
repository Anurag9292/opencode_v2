"""Composition root: wires the nine other components into a Session."""

import os
from typing import Callable

from ..interfaces.model import ModelProvider
from ..interfaces.tool import Tool
from ..types import Event, Message, PermissionRequest, Reply, new_id
from ..tools.builtin import default_tools
from .context import SimpleContextBuilder
from .events import InMemoryEventBus
from .loop import SimpleAgentLoop
from .permission import Rule, RulePermissionPolicy
from .registry import DictToolRegistry
from .store import JsonMessageStore
from .trace import JsonlTraceRecorder


class LocalSession:
    """Owns identity + wiring; contains almost no behavior itself."""

    def __init__(
        self,
        provider: ModelProvider,
        workdir: str,
        data_dir: str | None = None,
        tools: list[Tool] | None = None,
        rules: list[Rule] | None = None,
        asker: Callable[[PermissionRequest], Reply] | None = None,
        session_id: str | None = None,
    ) -> None:
        self.id = session_id or new_id("ses")
        data_dir = data_dir or os.path.join(workdir, ".miniagent")

        self.bus = InMemoryEventBus()
        self.trace = JsonlTraceRecorder(os.path.join(data_dir, "trace"))
        self.trace.attach(self.bus)
        self.store = JsonMessageStore(os.path.join(data_dir, "sessions"))
        self.permissions = RulePermissionPolicy(rules=rules, asker=asker, bus=self.bus)
        self.loop = SimpleAgentLoop(
            provider=provider,
            store=self.store,
            context=SimpleContextBuilder(workdir),
            registry=DictToolRegistry(tools if tools is not None else default_tools()),
            permissions=self.permissions,
            bus=self.bus,
            workdir=workdir,
        )
        self.bus.publish(Event(type="session.created", data={"session_id": self.id}))

    async def prompt(self, text: str) -> Message:
        return await self.loop.run(self.id, text)
