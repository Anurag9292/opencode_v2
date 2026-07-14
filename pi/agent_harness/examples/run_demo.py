"""End-to-end demo: a full tool-using turn, offline, with a scripted model.

Run from the agent_harness folder:

    python examples/run_demo.py

Flow demonstrated (mirrors pi's agent turn):
  user prompt -> assistant requests read_file -> tool executes -> tool result ->
  assistant produces final answer -> agent_end. Persistence + tracing happen via
  the EventBus, exactly like pi.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Allow running the file directly without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_harness import (  # noqa: E402
    ContextBuilder,
    DenyList,
    Event,
    JsonlMessageStore,
    PlannedResponse,
    ScriptedModelProvider,
    Session,
    TraceRecorder,
    default_tools,
    tool_call,
)
from agent_harness.events import MESSAGE_END, MESSAGE_UPDATE  # noqa: E402


def main() -> None:
    workdir = Path(tempfile.mkdtemp(prefix="agent_harness_demo_"))
    (workdir / "notes.txt").write_text("Ship the release on Friday. Owner: Mario.", encoding="utf-8")

    # Scripted model: turn 1 asks to read the file, turn 2 answers.
    model = ScriptedModelProvider(
        plan=[
            PlannedResponse(tool_calls=[tool_call("read_file", {"path": "notes.txt"})]),
            PlannedResponse(text="notes.txt says the release ships Friday, owned by Mario."),
        ]
    )

    session = Session.create(
        model=model,
        cwd=str(workdir),
        tools=default_tools(str(workdir)),
        store=JsonlMessageStore(str(workdir / "session.jsonl")),
        permission=DenyList(blocked=frozenset({"bash"})),  # gate bash to show the permission hook
        context_builder=ContextBuilder(
            cwd=str(workdir),
            context_files=[("AGENTS.md", "Prefer short, direct answers.")],
        ),
    )

    trace = TraceRecorder(path=str(workdir / "trace.jsonl"))
    trace.attach(session.bus)

    # Live-print streamed assistant text and finalized messages.
    def on_event(event: Event) -> None:
        if event.type == MESSAGE_UPDATE and "delta" in event.payload:
            sys.stdout.write(event.payload["delta"])
            sys.stdout.flush()
        elif event.type == MESSAGE_END:
            msg = event.payload["message"]
            if msg.role == "assistant" and msg.tool_calls:
                names = ", ".join(f"{tc.name}({tc.arguments})" for tc in msg.tool_calls)
                print(f"[assistant -> tool call] {names}")
            elif msg.role == "tool_result":
                preview = msg.content.replace("\n", " ")[:60]
                print(f"[tool result] {msg.tool_name}: {preview}")

    session.subscribe(on_event)

    print(f"workdir: {workdir}\n")
    print("=== prompt: 'Summarize notes.txt' ===")
    session.prompt("Summarize notes.txt")
    print("\n")

    print("=== persisted transcript ===")
    for msg in session.store.get_messages():
        print(f"  {msg.role:12} {msg.content[:60]!r}")

    print("\n=== event trace (summarized) ===")
    for record in trace.events:
        print(" ", record)

    print(f"\nSession file: {workdir / 'session.jsonl'}")
    print(f"Trace file:   {workdir / 'trace.jsonl'}")


if __name__ == "__main__":
    main()
