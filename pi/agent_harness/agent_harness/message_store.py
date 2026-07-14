"""MessageStore interface + in-memory and JSONL implementations.

pi origin: `SessionManager` (packages/coding-agent/src/core/session-manager.ts).
  - `append` mirrors `appendMessage` -> `_appendEntry` -> `_persist` (JSONL append).
  - Entries form a tree via `id`/`parent_id` (pi enables in-place branching).
  - `get_messages` mirrors `buildSessionContext().messages`.

Subtracted from pi: branching/compaction/model-change entries. We keep the tree
shape (id/parent_id) so branching could be layered on later, but only append a
linear path.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Protocol, runtime_checkable

from .types import Message, ToolCall


@runtime_checkable
class MessageStore(Protocol):
    session_id: str

    def append(self, message: Message) -> str: ...

    def get_messages(self) -> list[Message]: ...


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _message_to_entry(message: Message, entry_id: str, parent_id: str | None) -> dict:
    return {
        "type": "message",
        "id": entry_id,
        "parent_id": parent_id,
        "timestamp": time.time(),
        "message": asdict(message),
    }


def _message_from_dict(data: dict) -> Message:
    tool_calls = [ToolCall(**tc) for tc in data.get("tool_calls", [])]
    return Message(
        role=data["role"],
        content=data.get("content", ""),
        timestamp=data.get("timestamp", time.time()),
        tool_calls=tool_calls,
        stop_reason=data.get("stop_reason"),
        error_message=data.get("error_message"),
        tool_call_id=data.get("tool_call_id"),
        tool_name=data.get("tool_name"),
        is_error=data.get("is_error", False),
    )


class InMemoryMessageStore:
    """Keeps the transcript in memory only (pi: `SessionManager.inMemory()`)."""

    def __init__(self, session_id: str | None = None) -> None:
        self.session_id = session_id or _new_id()
        self._messages: list[Message] = []
        self._leaf_id: str | None = None

    def append(self, message: Message) -> str:
        entry_id = _new_id()
        self._messages.append(message)
        self._leaf_id = entry_id
        return entry_id

    def get_messages(self) -> list[Message]:
        return list(self._messages)


class JsonlMessageStore:
    """Persists the transcript as JSONL, one entry per line (pi's session file).

    Each line is a tree entry `{id, parent_id, timestamp, message}`. Loading an
    existing file restores the linear path so a session can be resumed.
    """

    def __init__(self, path: str, session_id: str | None = None) -> None:
        self.path = Path(path)
        self.session_id = session_id or self.path.stem or _new_id()
        self._messages: list[Message] = []
        self._leaf_id: str | None = None
        if self.path.exists():
            self._load()
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> None:
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("type") != "message":
                continue
            self._messages.append(_message_from_dict(entry["message"]))
            self._leaf_id = entry["id"]

    def append(self, message: Message) -> str:
        entry_id = _new_id()
        entry = _message_to_entry(message, entry_id, self._leaf_id)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        self._messages.append(message)
        self._leaf_id = entry_id
        return entry_id

    def get_messages(self) -> list[Message]:
        return list(self._messages)
