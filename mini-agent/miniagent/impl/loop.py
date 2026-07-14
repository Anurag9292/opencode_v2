"""The turn loop. Read this file first; everything else supports it."""

from ..interfaces.context import ContextBuilder
from ..interfaces.model import ModelProvider
from ..interfaces.store import MessageStore
from ..interfaces.tool import ToolRegistry
from ..types import (
    Event,
    Finish,
    Message,
    PermissionDenied,
    TextDelta,
    TextPart,
    ToolCallPart,
    ToolCallRequest,
    ToolContext,
    new_id,
)
from .events import InMemoryEventBus
from .permission import RulePermissionPolicy


class SimpleAgentLoop:
    def __init__(
        self,
        provider: ModelProvider,
        store: MessageStore,
        context: ContextBuilder,
        registry: ToolRegistry,
        permissions: RulePermissionPolicy,
        bus: InMemoryEventBus,
        workdir: str,
        max_turns: int = 25,
    ) -> None:
        self.provider = provider
        self.store = store
        self.context = context
        self.registry = registry
        self.permissions = permissions
        self.bus = bus
        self.workdir = workdir
        self.max_turns = max_turns

    async def run(self, session_id: str, user_text: str) -> Message:
        user = Message(id=new_id("msg"), session_id=session_id, role="user",
                       parts=[TextPart(text=user_text)])
        self.store.save(user)
        self._publish("message.created", session_id, message_id=user.id, role="user")

        for _ in range(self.max_turns):
            # The store is the source of truth: re-read history every turn.
            history = self.store.history(session_id)
            assistant = await self._one_model_turn(session_id, history)
            if assistant.finish_reason != "tool_calls":
                self._publish("session.idle", session_id)
                return assistant
            await self._execute_tool_calls(session_id, assistant)

        self._publish("session.error", session_id, error="max_turns exceeded")
        raise RuntimeError(f"agent exceeded {self.max_turns} turns without finishing")

    async def _one_model_turn(self, session_id: str, history: list[Message]) -> Message:
        """One model call: stream events, persist parts as they arrive."""
        assistant = Message(id=new_id("msg"), session_id=session_id, role="assistant")
        self.store.save(assistant)
        self._publish("message.created", session_id, message_id=assistant.id, role="assistant")

        model_context = self.context.build(session_id, history)
        async for event in self.provider.stream(model_context, self.registry.specs()):
            if isinstance(event, TextDelta):
                self._append_text(assistant, event.text)
                self._publish("message.part.delta", session_id,
                              message_id=assistant.id, text=event.text)
            if isinstance(event, ToolCallRequest):
                assistant.parts.append(ToolCallPart(
                    call_id=event.call_id, tool=event.tool, args=event.args,
                ))
            if isinstance(event, Finish):
                assistant.finish_reason = event.reason
                assistant.usage = event.usage
            # Persist after every event: a crash mid-turn loses nothing
            # that already streamed, and observers see live state.
            self.store.save(assistant)

        self._publish("message.updated", session_id,
                      message_id=assistant.id, finish_reason=assistant.finish_reason)
        return assistant

    async def _execute_tool_calls(self, session_id: str, assistant: Message) -> None:
        """Run requested tools sequentially, recording results on the parts.

        Every failure -- unknown tool, permission denial, tool exception --
        becomes model-readable output on the part instead of crashing the
        loop. The model sees the error next turn and can adapt.
        """
        for part in assistant.tool_calls():
            part.status = "running"
            self.store.save(assistant)
            self._publish("tool.started", session_id, tool=part.tool, call_id=part.call_id)

            tool = self.registry.get(part.tool)
            ctx = ToolContext(session_id=session_id, workdir=self.workdir,
                              ask=self.permissions.check)
            try:
                if tool is None:
                    raise ValueError(f"unknown tool: {part.tool}")
                result = await tool.execute(part.args, ctx)
                part.status = "completed"
                part.output = result.output
                part.title = result.title
            except PermissionDenied as denial:
                part.status = "error"
                part.error = f"Permission denied: {denial}. Do not retry this action; ask the user or try another approach."
            except Exception as failure:
                part.status = "error"
                part.error = f"{type(failure).__name__}: {failure}"

            self.store.save(assistant)
            self._publish("tool.finished", session_id, tool=part.tool,
                          call_id=part.call_id, status=part.status)

    def _append_text(self, message: Message, text: str) -> None:
        last = message.parts[-1] if message.parts else None
        if isinstance(last, TextPart):
            last.text += text
            return
        message.parts.append(TextPart(text=text))

    def _publish(self, type: str, session_id: str, **data: object) -> None:
        self.bus.publish(Event(type=type, data={"session_id": session_id, **data}))
