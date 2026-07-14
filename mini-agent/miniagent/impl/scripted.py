from typing import AsyncIterator

from ..types import ModelContext, ModelEvent, ToolSpec


class ScriptedProvider:
    """Deterministic fake provider for tests and offline demos.

    Constructed with a list of turns; each turn is a list of ModelEvents
    ending in a Finish. Lets you exercise the entire harness -- loop,
    tools, permissions, store, trace -- with zero network and zero cost,
    which is also exactly how the real harness's tests avoid mocks of
    anything except the network boundary.
    """

    def __init__(self, turns: list[list[ModelEvent]]) -> None:
        self.turns = turns
        self.calls: list[ModelContext] = []

    async def stream(
        self, context: ModelContext, tools: list[ToolSpec]
    ) -> AsyncIterator[ModelEvent]:
        self.calls.append(context)
        if not self.turns:
            raise AssertionError("ScriptedProvider ran out of turns")
        for event in self.turns.pop(0):
            yield event
