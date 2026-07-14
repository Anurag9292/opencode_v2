"""Tests for the harness turn loop.

These use the ScriptedModelProvider so the model behavior is deterministic; we
assert the *loop* does the right thing (persistence, tool dispatch, permission
gating, iteration cap, event emission) — the logic distilled from the OpenHands
architecture docs.

Run from this directory:  python -m pytest -q
"""

from __future__ import annotations

import os
import sys

# Make ``harness`` importable when running from the tests dir.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.impl import (  # noqa: E402
    ConfirmRisky,
    DictToolRegistry,
    InMemoryMessageStore,
    InMemoryTraceRecorder,
    NeverConfirm,
    ReactAgentLoop,
    ScriptedModelProvider,
    SimpleEventBus,
    SystemPromptContextBuilder,
    build_default_harness,
)
from harness.impl.session import AgentSession  # noqa: E402
from harness.tools.builtin import FinishTool, ReadFileTool, WriteFileTool  # noqa: E402
from harness.types import (  # noqa: E402
    EventKind,
    FinishReason,
    Message,
    ModelResponse,
    ToolCall,
    new_id,
)


def _loop(model, tools, permissions=None):
    store = InMemoryMessageStore()
    registry = DictToolRegistry()
    for tool in tools:
        registry.register(tool)
    bus = SimpleEventBus()
    trace = InMemoryTraceRecorder()
    bus.subscribe(trace.record)
    loop = ReactAgentLoop(
        model=model,
        store=store,
        context_builder=SystemPromptContextBuilder(registry),
        registry=registry,
        permissions=permissions or NeverConfirm(),
        bus=bus,
    )
    return loop, store, trace


def test_simple_answer_no_tools():
    model = ScriptedModelProvider(
        [ModelResponse(Message(role="assistant", content="hi there"), FinishReason.STOP)]
    )
    loop, store, trace = _loop(model, [])
    reply = loop.run("s1", "hello")

    assert reply.content == "hi there"
    roles = [m.role for m in store.history("s1")]
    assert roles == ["user", "assistant"]
    kinds = [e.kind for e in trace.export("s1")]
    assert EventKind.USER_MESSAGE in kinds
    assert EventKind.TURN_COMPLETE in kinds


def test_tool_call_then_observation_then_answer(tmp_path):
    (tmp_path / "hello.txt").write_text("file-body", encoding="utf-8")
    call = ToolCall(id=new_id("call"), name="read_file", arguments={"path": "hello.txt"})
    model = ScriptedModelProvider(
        [
            ModelResponse(Message(role="assistant", content="reading", tool_calls=[call]), FinishReason.TOOL_CALLS),
            ModelResponse(Message(role="assistant", content="final"), FinishReason.STOP),
        ]
    )
    loop, store, trace = _loop(model, [ReadFileTool(tmp_path)])
    reply = loop.run("s1", "read hello.txt")

    assert reply.content == "final"
    # user, assistant(tool_call), tool(observation), assistant(final)
    roles = [m.role for m in store.history("s1")]
    assert roles == ["user", "assistant", "tool", "assistant"]
    observation = store.history("s1")[2]
    assert observation.tool_result is not None
    assert observation.tool_result.content == "file-body"
    kinds = [e.kind for e in trace.export("s1")]
    assert EventKind.TOOL_CALL in kinds
    assert EventKind.TOOL_RESULT in kinds


def test_unknown_tool_becomes_error_observation_not_crash():
    call = ToolCall(id=new_id("call"), name="does_not_exist", arguments={})
    model = ScriptedModelProvider(
        [
            ModelResponse(Message(role="assistant", content="", tool_calls=[call]), FinishReason.TOOL_CALLS),
            ModelResponse(Message(role="assistant", content="ok"), FinishReason.STOP),
        ]
    )
    loop, store, _ = _loop(model, [])
    reply = loop.run("s1", "go")

    assert reply.content == "ok"
    observation = store.history("s1")[2]
    assert observation.tool_result.is_error
    assert "Unknown tool" in observation.tool_result.content


def test_permission_denies_write(tmp_path):
    call = ToolCall(id=new_id("call"), name="write_file", arguments={"path": "x.txt", "content": "data"})
    model = ScriptedModelProvider(
        [
            ModelResponse(Message(role="assistant", content="", tool_calls=[call]), FinishReason.TOOL_CALLS),
            ModelResponse(Message(role="assistant", content="done"), FinishReason.STOP),
        ]
    )
    # ConfirmRisky with no on_risky callback denies writes by default.
    loop, store, trace = _loop(model, [WriteFileTool(tmp_path)], permissions=ConfirmRisky())
    loop.run("s1", "write a file")

    observation = store.history("s1")[2]
    assert observation.tool_result.is_error
    assert "denied" in observation.tool_result.content
    assert not (tmp_path / "x.txt").exists()  # write never happened
    decisions = [e.payload["decision"] for e in trace.export("s1") if e.kind == EventKind.PERMISSION_CHECK]
    assert decisions == ["deny"]


def test_permission_allows_risky_when_confirmed(tmp_path):
    call = ToolCall(id=new_id("call"), name="write_file", arguments={"path": "y.txt", "content": "data"})
    model = ScriptedModelProvider(
        [
            ModelResponse(Message(role="assistant", content="", tool_calls=[call]), FinishReason.TOOL_CALLS),
            ModelResponse(Message(role="assistant", content="done"), FinishReason.STOP),
        ]
    )
    loop, store, _ = _loop(
        model, [WriteFileTool(tmp_path)], permissions=ConfirmRisky(on_risky=lambda c, s: True)
    )
    loop.run("s1", "write a file")

    assert (tmp_path / "y.txt").read_text() == "data"


def test_max_iterations_guard():
    # Model always asks for a tool -> would loop forever without the cap.
    def always_tool(messages, tools):
        call = ToolCall(id=new_id("call"), name="finish", arguments={"summary": "again"})
        return ModelResponse(Message(role="assistant", content="", tool_calls=[call]), FinishReason.TOOL_CALLS)

    class AlwaysToolModel:
        complete = staticmethod(always_tool)

    store = InMemoryMessageStore()
    registry = DictToolRegistry()
    registry.register(FinishTool())
    bus = SimpleEventBus()
    trace = InMemoryTraceRecorder()
    bus.subscribe(trace.record)
    loop = ReactAgentLoop(
        model=AlwaysToolModel(),
        store=store,
        context_builder=SystemPromptContextBuilder(registry),
        registry=registry,
        permissions=NeverConfirm(),
        bus=bus,
        max_iterations=3,
    )
    loop.run("s1", "go")

    iterations = [e for e in trace.export("s1") if e.kind == EventKind.ITERATION]
    assert len(iterations) == 3
    assert any(e.payload.get("reason") == "max_iterations_reached" for e in trace.export("s1"))


def test_history_is_source_of_truth_reread_each_iteration(tmp_path):
    # Two iterations: assert the second model call sees the observation from the first.
    seen_message_counts = []

    class SpyModel:
        def __init__(self):
            self._i = 0

        def complete(self, messages, tools):
            seen_message_counts.append(len(messages))
            self._i += 1
            if self._i == 1:
                call = ToolCall(id=new_id("call"), name="read_file", arguments={"path": "a.txt"})
                return ModelResponse(Message(role="assistant", content="", tool_calls=[call]), FinishReason.TOOL_CALLS)
            return ModelResponse(Message(role="assistant", content="fin"), FinishReason.STOP)

    (tmp_path / "a.txt").write_text("body", encoding="utf-8")
    loop, store, _ = _loop(SpyModel(), [ReadFileTool(tmp_path)])
    loop.run("s1", "read a.txt")

    # Second call must have more messages (it includes the tool observation).
    assert seen_message_counts[1] > seen_message_counts[0]


def test_build_default_harness_end_to_end(tmp_path):
    (tmp_path / "README.md").write_text("hello world", encoding="utf-8")
    harness = build_default_harness(workspace=tmp_path)
    session = harness.new_session()

    reply = session.send("read README.md")

    # EchoModelProvider reads then wraps up with the observation content.
    assert "hello world" in reply.content
    assert isinstance(session, AgentSession)
    assert len(harness.trace.export(session.id)) > 0
