"""AgentLoop — the heart of the harness: the turn loop.

``run(session_id, user_text)`` drives one user request to completion. The
reference implementation (``harness.impl.loop.ReactAgentLoop``) follows the
OpenHands turn shape distilled in ../../docs/agent-turn-sequence.md:

    persist user message                      (Step 1)
    while iterations < max_iterations:
        history = store.history(session_id)   # re-read: store is the truth
        messages = context_builder.build(...) # system prompt + instructions (Steps 3-4)
        response = model.complete(messages, tools)   # exactly one model call (Step 5)
        persist assistant message
        if response.finish_reason != TOOL_CALLS:
            return assistant                  # final response (Step 11)
        for call in response.message.tool_calls:      # tool-call detection (Step 6)
            decision = permissions.check(call, spec)   # permission gate
            result = tool.run(args) if ALLOW else denied-observation
            persist tool message              # result insertion
        # loop again with the new observations in history (next iteration)

Invariants worth teaching:
- exactly one model call per iteration
- history is re-read from the store every iteration
- tool failures / denials become observations, not crashes
- the loop terminates on a non-TOOL_CALLS finish reason or the iteration cap
  (the runaway-agent guard)
- every step publishes an Event (persisted by the TraceRecorder)
"""

from __future__ import annotations

from typing import Protocol

from ..types import Message


class AgentLoop(Protocol):
    def run(self, session_id: str, user_text: str) -> Message: ...
