"""Interactive CLI: python -m miniagent [workdir]

Requires ANTHROPIC_API_KEY. Streams assistant text, prints tool activity,
and prompts on permission asks -- all driven purely by bus events, which
demonstrates that a UI is just another subscriber.
"""

import asyncio
import os
import sys

from .impl.anthropic import AnthropicProvider
from .impl.session import LocalSession
from .types import Event, PermissionRequest, Reply


def ask_human(request: PermissionRequest) -> Reply:
    print(f"\n[permission] {request.tool} wants {request.action}: {request.pattern}")
    answer = input("  allow once (y) / always (a) / reject (n)? ").strip().lower()
    if answer == "a":
        return "always"
    if answer == "y":
        return "once"
    return "reject"


def render(event: Event) -> None:
    if event.type == "message.part.delta":
        print(event.data["text"], end="", flush=True)
    if event.type == "tool.started":
        print(f"\n[tool] {event.data['tool']} ...", flush=True)
    if event.type == "tool.finished":
        print(f"[tool] {event.data['tool']} -> {event.data['status']}", flush=True)


async def main() -> None:
    workdir = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
    session = LocalSession(provider=AnthropicProvider(), workdir=workdir, asker=ask_human)
    for type in ["message.part.delta", "tool.started", "tool.finished"]:
        session.bus.subscribe(type, render)

    print(f"miniagent session {session.id} in {workdir} (ctrl-d to exit)")
    while True:
        try:
            text = input("\n> ").strip()
        except EOFError:
            return
        if not text:
            continue
        await session.prompt(text)
        print()


if __name__ == "__main__":
    asyncio.run(main())
