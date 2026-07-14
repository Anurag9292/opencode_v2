import dataclasses
import json
import os

from ..types import FinishReason, Message, Part, TextPart, ToolCallPart


class JsonMessageStore:
    """One JSON file per session under a root directory.

    Naive on purpose: rewrite-whole-file persistence is easy to inspect
    (open the file, read the transcript) and easy to replace with SQLite
    later because the interface is only save() + history().
    """

    def __init__(self, root: str) -> None:
        self.root = root
        os.makedirs(root, exist_ok=True)

    def save(self, message: Message) -> None:
        messages = self.history(message.session_id)
        replaced = [m if m.id != message.id else message for m in messages]
        if message.id not in [m.id for m in messages]:
            replaced.append(message)
        path = self._path(message.session_id)
        with open(path, "w") as f:
            json.dump([dataclasses.asdict(m) for m in replaced], f, indent=2)

    def history(self, session_id: str) -> list[Message]:
        path = self._path(session_id)
        if not os.path.exists(path):
            return []
        with open(path) as f:
            raw = json.load(f)
        return [self._decode(m) for m in raw]

    def _path(self, session_id: str) -> str:
        return os.path.join(self.root, f"{session_id}.json")

    def _decode(self, raw: dict) -> Message:
        parts: list[Part] = [
            TextPart(text=p["text"]) if p["type"] == "text"
            else ToolCallPart(**{k: v for k, v in p.items() if k != "type"})
            for p in raw["parts"]
        ]
        finish: FinishReason | None = raw.get("finish_reason")
        return Message(
            id=raw["id"],
            session_id=raw["session_id"],
            role=raw["role"],
            parts=parts,
            created_at=raw["created_at"],
            finish_reason=finish,
            usage=raw.get("usage", {}),
        )
