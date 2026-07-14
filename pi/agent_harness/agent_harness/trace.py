"""TraceRecorder: observability sink that subscribes to the EventBus.

pi origin: the observability story in packages/agent/docs/observability.md plus the
fact that session persistence itself is driven by an event subscriber
(`AgentSession._handleAgentEvent`). Here the recorder is a pure listener: it never
mutates state, it only records the event stream for debugging / eval.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .events import Event, EventBus


def _summarize(event: Event) -> dict[str, Any]:
    """Compact, JSON-serializable view of an event (avoids dumping huge payloads)."""

    data: dict[str, Any] = {"t": round(time.time(), 3), "type": event.type}
    payload = event.payload
    if "message" in payload:
        msg = payload["message"]
        data["role"] = getattr(msg, "role", None)
        if getattr(msg, "tool_calls", None):
            data["tool_calls"] = [tc.name for tc in msg.tool_calls]
        if getattr(msg, "stop_reason", None):
            data["stop_reason"] = msg.stop_reason
    for key in ("tool_name", "is_error", "turn_index"):
        if key in payload:
            data[key] = payload[key]
    return data


@dataclass
class TraceRecorder:
    """Records a summarized event trace. Optionally mirrors it to a JSONL file."""

    path: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)

    def attach(self, bus: EventBus):
        if self.path:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            # Truncate any prior trace for a fresh run.
            Path(self.path).write_text("", encoding="utf-8")
        return bus.subscribe(self._on_event)

    def _on_event(self, event: Event) -> None:
        record = _summarize(event)
        self.events.append(record)
        if self.path:
            with Path(self.path).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")

    def dump(self) -> str:
        return "\n".join(json.dumps(e) for e in self.events)
