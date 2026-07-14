"""agent_harness — a minimal educational coding-agent harness.

Design derived from the OpenHands architecture docs in
``openhands_all/docs`` (agent-turn-sequence.md, core-module-map.md). It is an
independent, dependency-free reimagining of the *turn logic* — it does NOT copy
OpenHands source.

Public surface:
    from harness.impl import build_default_harness
    h = build_default_harness()
    session = h.new_session()
    reply = session.send("read README.md")
    print(reply.content)

See the interfaces in ``harness.interfaces`` for the ten roles and
``harness.impl.loop.ReactAgentLoop`` for the turn loop.
"""

from . import interfaces, impl, tools, types

__all__ = ["interfaces", "impl", "tools", "types"]
