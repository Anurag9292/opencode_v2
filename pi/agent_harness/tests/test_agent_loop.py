"""Tests for the core agent loop, exercised with the scripted model provider.

Run from the agent_harness folder:

    python -m pytest tests/ -q          # if pytest is available
    python tests/test_agent_loop.py     # plain-stdlib fallback runner
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_harness import (  # noqa: E402
    AllowAll,
    ContextBuilder,
    DenyList,
    InMemoryMessageStore,
    JsonlMessageStore,
    PlannedResponse,
    ScriptedModelProvider,
    Session,
    ToolRegistry,
    default_tools,
    tool_call,
)
from agent_harness.agent_loop import AgentLoop, AgentLoopConfig  # noqa: E402
from agent_harness.events import (  # noqa: E402
    AGENT_END,
    AGENT_START,
    TOOL_EXECUTION_END,
    EventBus,
)
from agent_harness.types import Message  # noqa: E402


def _workdir_with_notes() -> Path:
    workdir = Path(tempfile.mkdtemp(prefix="agent_harness_test_"))
    (workdir / "notes.txt").write_text("hello world", encoding="utf-8")
    return workdir


def test_full_tool_turn_produces_final_answer() -> None:
    workdir = _workdir_with_notes()
    model = ScriptedModelProvider(
        plan=[
            PlannedResponse(tool_calls=[tool_call("read_file", {"path": "notes.txt"})]),
            PlannedResponse(text="The file says hello world."),
        ]
    )
    session = Session.create(model=model, cwd=str(workdir), tools=default_tools(str(workdir)))
    new_messages = session.prompt("read notes")

    roles = [m.role for m in new_messages]
    assert roles == ["user", "assistant", "tool_result", "assistant"], roles

    tool_result = new_messages[2]
    assert tool_result.tool_name == "read_file"
    assert "hello world" in tool_result.content
    assert not tool_result.is_error

    final = new_messages[3]
    assert final.role == "assistant"
    assert final.stop_reason == "end"
    assert "hello world" in final.content


def test_permission_denied_produces_error_result_and_loop_recovers() -> None:
    workdir = _workdir_with_notes()
    model = ScriptedModelProvider(
        plan=[
            PlannedResponse(tool_calls=[tool_call("bash", {"command": "rm -rf /"})]),
            PlannedResponse(text="Understood, I will not run that."),
        ]
    )
    session = Session.create(
        model=model,
        cwd=str(workdir),
        tools=default_tools(str(workdir)),
        permission=DenyList(blocked=frozenset({"bash"})),
    )
    new_messages = session.prompt("delete everything")

    tool_result = new_messages[2]
    assert tool_result.is_error
    assert "disabled by policy" in tool_result.content
    # Loop continued and produced a final assistant turn.
    assert new_messages[-1].role == "assistant"
    assert new_messages[-1].stop_reason == "end"


def test_invalid_arguments_are_rejected_before_execute() -> None:
    workdir = _workdir_with_notes()
    model = ScriptedModelProvider(
        plan=[
            PlannedResponse(tool_calls=[tool_call("read_file", {})]),  # missing required 'path'
            PlannedResponse(text="Sorry about that."),
        ]
    )
    session = Session.create(model=model, cwd=str(workdir), tools=default_tools(str(workdir)))
    new_messages = session.prompt("read")

    tool_result = new_messages[2]
    assert tool_result.is_error
    assert "Missing required argument 'path'" in tool_result.content


def test_persistence_roundtrip_with_jsonl_store() -> None:
    workdir = _workdir_with_notes()
    session_file = workdir / "session.jsonl"
    model = ScriptedModelProvider(
        plan=[
            PlannedResponse(tool_calls=[tool_call("read_file", {"path": "notes.txt"})]),
            PlannedResponse(text="Done."),
        ]
    )
    session = Session.create(
        model=model, cwd=str(workdir), tools=default_tools(str(workdir)), store=JsonlMessageStore(str(session_file))
    )
    session.prompt("read notes")

    # New store over the same file resumes the full transcript.
    resumed = JsonlMessageStore(str(session_file))
    roles = [m.role for m in resumed.get_messages()]
    assert roles == ["user", "assistant", "tool_result", "assistant"], roles


def test_max_iterations_guard_stops_runaway_tool_loops() -> None:
    workdir = _workdir_with_notes()
    # Model always asks to read the file -> would loop forever without the guard.
    model = ScriptedModelProvider(plan=[PlannedResponse(tool_calls=[tool_call("read_file", {"path": "notes.txt"})])] * 100)
    bus = EventBus()
    seen = {"agent_end": 0}
    bus.subscribe(lambda e: seen.__setitem__("agent_end", seen["agent_end"] + (1 if e.type == AGENT_END else 0)))

    registry = ToolRegistry(default_tools(str(workdir)))
    loop = AgentLoop(
        model=model,
        context_builder=ContextBuilder(cwd=str(workdir)),
        registry=registry,
        bus=bus,
        permission=AllowAll(),
        config=AgentLoopConfig(max_iterations=3),
    )
    history: list[Message] = []
    loop.run([Message(role="user", content="go")], history)
    assert seen["agent_end"] == 1  # loop terminated cleanly


def _run_all() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERROR {test.__name__}: {exc}")
    if failures:
        print(f"\n{failures} test(s) failed")
        sys.exit(1)
    print(f"\nAll {len(tests)} tests passed")


if __name__ == "__main__":
    _run_all()
