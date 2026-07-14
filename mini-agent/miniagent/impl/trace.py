import dataclasses
import json
import os

from ..types import Event

from .events import InMemoryEventBus


class JsonlTraceRecorder:
    """Append-only JSONL trace, one file per session.

    Attaches to the bus as a wildcard subscriber, so tracing costs the
    loop nothing and can be removed without touching any component.
    """

    def __init__(self, root: str) -> None:
        self.root = root
        os.makedirs(root, exist_ok=True)

    def attach(self, bus: InMemoryEventBus) -> None:
        bus.subscribe("*", self.record)

    def record(self, event: Event) -> None:
        session_id = event.data.get("session_id", "global")
        with open(os.path.join(self.root, f"{session_id}.jsonl"), "a") as f:
            f.write(json.dumps(dataclasses.asdict(event)) + "\n")

    def read(self, session_id: str) -> list[Event]:
        path = os.path.join(self.root, f"{session_id}.jsonl")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [Event(**json.loads(line)) for line in f if line.strip()]
