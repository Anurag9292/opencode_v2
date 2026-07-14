"""CLI / demo entrypoint.

Run a scripted end-to-end turn (no API key needed) and print the trace:

    python -m harness            # scripted demo showing tool-call -> observation -> answer
    python -m harness --repl     # interactive REPL using the EchoModelProvider

The scripted demo is the clearest illustration of the OpenHands turn shape.
"""

from __future__ import annotations

import sys

from .impl import build_default_harness
from .impl.providers import ScriptedModelProvider
from .types import FinishReason, Message, ModelResponse, ToolCall, new_id


def _scripted_demo() -> None:
    # A three-step trajectory: read a file -> observe -> final answer.
    script = [
        ModelResponse(
            Message(
                role="assistant",
                content="I'll list the workspace first.",
                tool_calls=[ToolCall(id=new_id("call"), name="list_dir", arguments={"path": "."})],
            ),
            FinishReason.TOOL_CALLS,
        ),
        ModelResponse(
            Message(role="assistant", content="Here is what I found in the workspace."),
            FinishReason.STOP,
        ),
    ]
    harness = build_default_harness(model=ScriptedModelProvider(script), workspace=".")
    session = harness.new_session()

    reply = session.send("What files are here?")

    print("=== FINAL ANSWER ===")
    print(reply.content)
    print("\n=== TRACE ===")
    for event in harness.trace.export(session.id):
        print(f"  {event.kind.value:18} {event.payload}")
    print("\n=== TRANSCRIPT ===")
    for message in session.history():
        tag = message.role.upper()
        extra = f" tool_calls={[c.name for c in message.tool_calls]}" if message.tool_calls else ""
        print(f"  [{tag}]{extra} {message.content[:80]}")


def _repl() -> None:
    harness = build_default_harness(workspace=".")
    session = harness.new_session()
    print(f"harness REPL (session {session.id}); Ctrl-D to exit.")
    print('Try: "read README.md"')
    while True:
        try:
            user_text = input("you> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        reply = session.send(user_text)
        print(f"agent> {reply.content}")


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if "--repl" in argv:
        _repl()
    else:
        _scripted_demo()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
