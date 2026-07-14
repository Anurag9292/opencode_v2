"""ReactAgentLoop — the reference turn loop.

This is the component that "gets the logic right" from the OpenHands harness
flow (see ../../docs/agent-turn-sequence.md). It wires the ten interfaces
together into a single, readable loop and emits an Event at every meaningful
step so the whole run is observable and replayable.

The loop deliberately mirrors the documented OpenHands turn shape:

    Step 1  persist the user message                     -> USER_MESSAGE
    (loop, up to max_iterations)
    Step 3-4 build context (system prompt + instructions) -> MODEL_REQUEST
    Step 5  one model call                                -> MODEL_RESPONSE
            persist assistant message
    Step 6  if finish_reason != TOOL_CALLS -> final answer -> TURN_COMPLETE
            for each detected tool call:                   -> TOOL_CALL
                permission check                           -> PERMISSION_CHECK
                execute (or synthesize denial/error)       -> TOOL_RESULT
                persist tool observation message
    Step 11 return the final assistant message

Key invariants (enforced here, not just documented):
- exactly one model call per iteration
- history is re-read from the store every iteration (store is the source of truth)
- tool failures/denials/unknown-tools become observations, never exceptions
- a hard ``max_iterations`` guard prevents a runaway agent
"""

from __future__ import annotations

from ..interfaces.context import ContextBuilder
from ..interfaces.events import EventBus
from ..interfaces.model import ModelProvider
from ..interfaces.permission import Decision, PermissionPolicy
from ..interfaces.store import MessageStore
from ..interfaces.tool import ToolRegistry
from ..types import (
    Event,
    EventKind,
    FinishReason,
    Message,
    ToolCall,
    ToolResult,
)


class ReactAgentLoop:
    def __init__(
        self,
        model: ModelProvider,
        store: MessageStore,
        context_builder: ContextBuilder,
        registry: ToolRegistry,
        permissions: PermissionPolicy,
        bus: EventBus,
        max_iterations: int = 20,
    ) -> None:
        self.model = model
        self.store = store
        self.context_builder = context_builder
        self.registry = registry
        self.permissions = permissions
        self.bus = bus
        self.max_iterations = max_iterations

    def run(self, session_id: str, user_text: str) -> Message:
        # Step 1: admit the user input into the durable transcript.
        user_msg = self.store.append(session_id, Message(role="user", content=user_text))
        self._emit(session_id, EventKind.USER_MESSAGE, {"text": user_text, "message_id": user_msg.id})

        last_assistant: Message | None = None

        for iteration in range(1, self.max_iterations + 1):
            self._emit(session_id, EventKind.ITERATION, {"iteration": iteration})

            # Steps 3-4: re-read history and build the model context.
            history = self.store.history(session_id)
            messages = self.context_builder.build(session_id, history)
            specs = self.registry.specs()
            self._emit(
                session_id,
                EventKind.MODEL_REQUEST,
                {"iteration": iteration, "message_count": len(messages), "tool_count": len(specs)},
            )

            # Step 5: exactly one model call.
            response = self.model.complete(messages, specs)
            assistant = response.message
            assistant.role = "assistant"
            self.store.append(session_id, assistant)
            last_assistant = assistant
            self._emit(
                session_id,
                EventKind.MODEL_RESPONSE,
                {
                    "iteration": iteration,
                    "finish_reason": response.finish_reason.value,
                    "tool_calls": [c.name for c in assistant.tool_calls],
                    "content_preview": assistant.content[:200],
                },
            )

            # Step 6/11: no tool calls -> this is the final response.
            if response.finish_reason != FinishReason.TOOL_CALLS or not assistant.tool_calls:
                self._emit(session_id, EventKind.TURN_COMPLETE, {"iterations": iteration})
                return assistant

            # Step 6: detect, gate, execute each tool call; insert observations.
            for call in assistant.tool_calls:
                self._handle_tool_call(session_id, call)
            # loop again: observations are now in history -> next model iteration

        # Runaway guard: hit the iteration cap without a final answer.
        self._emit(session_id, EventKind.ERROR, {"reason": "max_iterations_reached"})
        capped = self.store.append(
            session_id,
            Message(
                role="assistant",
                content=f"Stopped after {self.max_iterations} iterations without finishing.",
            ),
        )
        self._emit(session_id, EventKind.TURN_COMPLETE, {"iterations": self.max_iterations, "capped": True})
        return last_assistant or capped

    def _handle_tool_call(self, session_id: str, call: ToolCall) -> None:
        tool = self.registry.get(call.name)
        spec = tool.spec if tool is not None else None
        self._emit(session_id, EventKind.TOOL_CALL, {"call_id": call.id, "name": call.name, "arguments": call.arguments})

        # Unknown tool -> observation, not a crash.
        if tool is None:
            self._insert_observation(
                session_id,
                ToolResult(call_id=call.id, content=f"Unknown tool: {call.name}", is_error=True),
            )
            return

        # Permission gate (Step 6).
        decision = self.permissions.check(call, spec)
        self._emit(session_id, EventKind.PERMISSION_CHECK, {"call_id": call.id, "name": call.name, "decision": decision.value})
        if decision != Decision.ALLOW:
            self._insert_observation(
                session_id,
                ToolResult(call_id=call.id, content=f"Tool `{call.name}` denied by permission policy.", is_error=True),
            )
            return

        # Execute. A tool should return an error result rather than raise, but we
        # defend anyway so one bad tool never crashes the loop. We pass the
        # call id via a reserved key so the tool can correlate its result.
        arguments = {**call.arguments, "__call_id__": call.id}
        try:
            result = tool.run(arguments)
        except Exception as exc:  # defensive: convert to observation
            result = ToolResult(call_id=call.id, content=f"Tool `{call.name}` raised: {exc!r}", is_error=True)
        # Ensure the observation is always correlated to the originating call.
        if not result.call_id:
            result.call_id = call.id
        self._insert_observation(session_id, result)

    def _insert_observation(self, session_id: str, result: ToolResult) -> None:
        # Result insertion (Step 6): store the observation as a tool message so
        # the next model iteration sees it in history.
        self.store.append(
            session_id,
            Message(role="tool", content=result.content, tool_result=result),
        )
        self._emit(
            session_id,
            EventKind.TOOL_RESULT,
            {"call_id": result.call_id, "is_error": result.is_error, "content_preview": result.content[:200]},
        )

    def _emit(self, session_id: str, kind: EventKind, payload: dict) -> None:
        self.bus.publish(Event(kind=kind, session_id=session_id, payload=payload))
