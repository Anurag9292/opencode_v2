from typing import Protocol

from ..types import Message


class AgentLoop(Protocol):
    """The heart of the harness: the turn loop.

    run() drives one user request to completion:

        while True:
            history = store.history(session_id)
            if finished(history): return last_assistant
            context = context_builder.build(session_id, history)
            stream one model call, persisting parts as they arrive
            execute any requested tool calls (through permissions)
            # loop: tool results are in history now, model goes again

    Invariants worth teaching:
    - exactly one model call per iteration
    - history is re-read from the store every iteration (the store is
      the source of truth, not local state)
    - the loop terminates when finish_reason != "tool_calls", or when
      max_turns is hit (runaway-agent guard)
    - tool failures become tool output, not loop crashes
    """

    async def run(self, session_id: str, user_text: str) -> Message: ...
