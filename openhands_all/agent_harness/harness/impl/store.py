"""MessageStore implementations: in-memory and file-backed.

Both keep the transcript as the source of truth (see interfaces/store.py). The
file store demonstrates the persistence step (docs Step 8) using one JSON file
per session; it is intentionally simple, not optimized.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ..types import Message, ToolCall, ToolResult


class InMemoryMessageStore:
    def __init__(self) -> None:
        self._sessions: dict[str, list[Message]] = {}

    def create_session(self, session_id: str) -> None:
        self._sessions.setdefault(session_id, [])

    def sessions(self) -> list[str]:
        return list(self._sessions.keys())

    def append(self, session_id: str, message: Message) -> Message:
        self._sessions.setdefault(session_id, []).append(message)
        return message

    def history(self, session_id: str) -> list[Message]:
        # return a shallow copy so callers cannot mutate the stored list
        return list(self._sessions.get(session_id, []))


class FileMessageStore:
    """One ``{session_id}.json`` file per conversation under ``root``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.root / f"{session_id}.json"

    def create_session(self, session_id: str) -> None:
        path = self._path(session_id)
        if not path.exists():
            path.write_text("[]")

    def sessions(self) -> list[str]:
        return [p.stem for p in self.root.glob("*.json")]

    def append(self, session_id: str, message: Message) -> Message:
        history = self.history(session_id)
        history.append(message)
        self._path(session_id).write_text(
            json.dumps([_dump(m) for m in history], indent=2)
        )
        return message

    def history(self, session_id: str) -> list[Message]:
        path = self._path(session_id)
        if not path.exists():
            return []
        return [_load(d) for d in json.loads(path.read_text())]


def _dump(message: Message) -> dict:
    return asdict(message)


def _load(data: dict) -> Message:
    tool_calls = [ToolCall(**tc) for tc in data.get("tool_calls", [])]
    raw_result = data.get("tool_result")
    tool_result = ToolResult(**raw_result) if raw_result else None
    return Message(
        role=data["role"],
        content=data.get("content", ""),
        tool_calls=tool_calls,
        tool_result=tool_result,
        id=data["id"],
        created_at=data["created_at"],
    )
