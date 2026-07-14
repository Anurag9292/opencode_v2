"""AgentLoop: the core turn loop.

pi origin: `runLoop` + `streamAssistantResponse` + `executeToolCalls` +
`prepareToolCall` + `finalizeExecutedToolCall` (packages/agent/src/agent-loop.ts).

Responsibilities (model + tools only; persistence lives in Session, like pi's
split between agent-core and AgentSession):
  1. Emit lifecycle events (agent_start / turn_start / message_* / tool_* / turn_end / agent_end).
  2. Stream one assistant message per turn from the ModelProvider.
  3. Detect tool calls, run the permission gate, validate args, execute, and feed
     tool results back for the next turn.
  4. Repeat until the assistant stops requesting tools (or a terminate/limit).

Subtracted from pi: steering/follow-up queues, parallel tool execution, retries,
and compaction. Extension points are marked so these can be layered on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .context_builder import ContextBuilder
from .events import (
    AGENT_END,
    AGENT_START,
    MESSAGE_END,
    MESSAGE_START,
    MESSAGE_UPDATE,
    TOOL_EXECUTION_END,
    TOOL_EXECUTION_START,
    TOOL_EXECUTION_UPDATE,
    TURN_END,
    TURN_START,
    Event,
    EventBus,
)
from .model_provider import ModelProvider
from .permissions import AllowAll, PermissionPolicy
from .tools import ToolRegistry, ToolValidationError, validate_arguments
from .types import Message, ToolCall, ToolResult


@dataclass
class AgentLoopConfig:
    # Safety valve absent in pi's core loop but essential for a runaway guard.
    max_iterations: int = 20


@dataclass
class _ToolBatch:
    results: list[Message]
    terminate: bool


class AgentLoop:
    def __init__(
        self,
        model: ModelProvider,
        context_builder: ContextBuilder,
        registry: ToolRegistry,
        bus: EventBus,
        permission: PermissionPolicy | None = None,
        config: AgentLoopConfig | None = None,
    ) -> None:
        self.model = model
        self.context_builder = context_builder
        self.registry = registry
        self.bus = bus
        self.permission = permission or AllowAll()
        self.config = config or AgentLoopConfig()

    # -- public entry ------------------------------------------------------

    def run(self, prompts: list[Message], history: list[Message]) -> list[Message]:
        """Run to completion. `history` is the mutable transcript (like pi's context.messages).

        Returns the list of newly produced messages (prompts + assistant + tool results).
        """

        new_messages: list[Message] = list(prompts)
        self.bus.emit(Event(AGENT_START))
        self.bus.emit(Event(TURN_START, {"turn_index": 0}))
        for prompt in prompts:
            history.append(prompt)
            self.bus.emit(Event(MESSAGE_START, {"message": prompt}))
            self.bus.emit(Event(MESSAGE_END, {"message": prompt}))

        turn_index = 0
        first_turn = True
        has_more = True
        while has_more:
            if not first_turn:
                turn_index += 1
                self.bus.emit(Event(TURN_START, {"turn_index": turn_index}))
            first_turn = False

            if turn_index >= self.config.max_iterations:
                break

            assistant = self._stream_assistant(history)
            history.append(assistant)
            new_messages.append(assistant)

            if assistant.stop_reason in ("error", "aborted"):
                self.bus.emit(Event(TURN_END, {"message": assistant, "tool_results": [], "turn_index": turn_index}))
                break

            results: list[Message] = []
            has_more = False
            if assistant.has_tool_calls():
                if assistant.stop_reason == "length":
                    # pi: a truncated message may carry incomplete tool args -> fail them all.
                    batch = self._fail_truncated(assistant.tool_calls)
                else:
                    batch = self._execute_tools(assistant, history)
                results = batch.results
                has_more = not batch.terminate
                for result in results:
                    history.append(result)
                    new_messages.append(result)

            self.bus.emit(Event(TURN_END, {"message": assistant, "tool_results": results, "turn_index": turn_index}))
            # Extension point: steering / follow-up message polling would go here (pi).

        self.bus.emit(Event(AGENT_END, {"messages": new_messages}))
        return new_messages

    # -- assistant streaming ----------------------------------------------

    def _stream_assistant(self, history: list[Message]) -> Message:
        """Mirror of `streamAssistantResponse`: assemble one AssistantMessage from the stream."""

        context = self.context_builder.build(history, self.registry)
        partial = Message(role="assistant", content="")
        self.bus.emit(Event(MESSAGE_START, {"message": partial}))

        for event in self.model.stream(context):
            if event.type == "text_delta":
                partial.content += event.delta
                self.bus.emit(Event(MESSAGE_UPDATE, {"message": partial, "delta": event.delta}))
            elif event.type == "toolcall" and event.tool_call is not None:
                partial.tool_calls.append(event.tool_call)
                self.bus.emit(Event(MESSAGE_UPDATE, {"message": partial, "tool_call": event.tool_call}))
            elif event.type == "done":
                partial.stop_reason = event.stop_reason or ("tool_use" if partial.tool_calls else "end")
            elif event.type == "error":
                partial.stop_reason = "error"
                partial.error_message = event.error

        self.bus.emit(Event(MESSAGE_END, {"message": partial}))
        return partial

    # -- tool execution ----------------------------------------------------

    def _execute_tools(self, assistant: Message, history: list[Message]) -> _ToolBatch:
        """Sequential tool execution mirroring pi's prepare -> execute -> finalize."""

        results: list[Message] = []
        terminate_flags: list[bool] = []

        for call in assistant.tool_calls:
            self.bus.emit(
                Event(TOOL_EXECUTION_START, {"tool_call_id": call.id, "tool_name": call.name, "args": call.arguments})
            )
            result = self._run_single_tool(call)
            terminate_flags.append(result.terminate)

            self.bus.emit(
                Event(
                    TOOL_EXECUTION_END,
                    {"tool_call_id": call.id, "tool_name": call.name, "result": result, "is_error": result.is_error},
                )
            )

            message = Message(
                role="tool_result",
                content=result.content,
                tool_call_id=call.id,
                tool_name=call.name,
                is_error=result.is_error,
            )
            self.bus.emit(Event(MESSAGE_START, {"message": message}))
            self.bus.emit(Event(MESSAGE_END, {"message": message}))
            results.append(message)

        terminate = len(terminate_flags) > 0 and all(terminate_flags)
        return _ToolBatch(results=results, terminate=terminate)

    def _run_single_tool(self, call: ToolCall) -> ToolResult:
        """prepare (lookup + validate + permission) -> execute. Errors -> error result."""

        tool = self.registry.get(call.name)
        if tool is None:
            return ToolResult(content=f"Tool '{call.name}' not found", is_error=True)

        # Permission gate (pi: beforeToolCall / tool_call hook).
        decision = self.permission.check(call)
        if not decision.allow:
            return ToolResult(content=decision.reason or "Tool execution was blocked", is_error=True)

        # Argument validation (pi: validateToolArguments).
        try:
            args = validate_arguments(tool, call.arguments)
        except ToolValidationError as exc:
            return ToolResult(content=str(exc), is_error=True)

        def on_update(partial: ToolResult) -> None:
            self.bus.emit(
                Event(TOOL_EXECUTION_UPDATE, {"tool_call_id": call.id, "tool_name": call.name, "partial": partial})
            )

        try:
            return tool.execute(call.id, args, on_update)
        except Exception as exc:  # pi: thrown errors become isError tool results.
            return ToolResult(content=str(exc), is_error=True)

    def _fail_truncated(self, tool_calls: list[ToolCall]) -> _ToolBatch:
        """pi: failToolCallsFromTruncatedMessage - never execute possibly-truncated calls."""

        results: list[Message] = []
        for call in tool_calls:
            self.bus.emit(
                Event(TOOL_EXECUTION_START, {"tool_call_id": call.id, "tool_name": call.name, "args": call.arguments})
            )
            result = ToolResult(
                content=(
                    f"Tool call '{call.name}' was not executed: the response hit the output token "
                    "limit, so arguments may be truncated. Re-issue with complete arguments."
                ),
                is_error=True,
            )
            self.bus.emit(
                Event(
                    TOOL_EXECUTION_END,
                    {"tool_call_id": call.id, "tool_name": call.name, "result": result, "is_error": True},
                )
            )
            message = Message(
                role="tool_result", content=result.content, tool_call_id=call.id, tool_name=call.name, is_error=True
            )
            self.bus.emit(Event(MESSAGE_START, {"message": message}))
            self.bus.emit(Event(MESSAGE_END, {"message": message}))
            results.append(message)
        return _ToolBatch(results=results, terminate=False)
