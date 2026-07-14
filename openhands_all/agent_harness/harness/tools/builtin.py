"""A small set of builtin tools.

Each tool implements the ``Tool`` protocol: it exposes a ``spec`` (advertised to
the model) and a ``run`` (executed by the loop after the permission gate). Tools
return ``ToolResult`` for both success and expected failure — they do not raise
for bad input, so a mistaken call becomes an observation the model can recover
from (see interfaces/tool.py).

All filesystem tools are confined to a ``workspace`` root and reject path
traversal, a minimal version of OpenHands' sandbox confinement.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..types import ToolResult, ToolSpec


class _WorkspaceTool:
    """Shared helper: resolve a path safely inside the workspace root."""

    def __init__(self, workspace: str | Path = ".") -> None:
        self.workspace = Path(workspace).resolve()

    def _resolve(self, raw: str) -> Path:
        candidate = (self.workspace / raw).resolve()
        if self.workspace not in candidate.parents and candidate != self.workspace:
            raise ValueError(f"path escapes workspace: {raw}")
        return candidate


class ReadFileTool(_WorkspaceTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="read_file",
            description="Read a UTF-8 text file relative to the workspace.",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            writes=False,
        )

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        call_id = str(arguments.get("__call_id__", ""))
        try:
            path = self._resolve(str(arguments["path"]))
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            return ToolResult(call_id=call_id, content=f"read_file error: {exc}", is_error=True)
        return ToolResult(call_id=call_id, content=text)


class ListDirTool(_WorkspaceTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="list_dir",
            description="List entries of a directory relative to the workspace.",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            writes=False,
        )

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        call_id = str(arguments.get("__call_id__", ""))
        try:
            path = self._resolve(str(arguments.get("path", ".")))
            entries = sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir())
        except Exception as exc:
            return ToolResult(call_id=call_id, content=f"list_dir error: {exc}", is_error=True)
        return ToolResult(call_id=call_id, content="\n".join(entries) or "(empty)")


class WriteFileTool(_WorkspaceTool):
    """A side-effecting tool: ``spec.writes = True`` so ConfirmRisky gates it."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="write_file",
            description="Write UTF-8 text to a file relative to the workspace (creates or overwrites).",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
            writes=True,
        )

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        call_id = str(arguments.get("__call_id__", ""))
        try:
            path = self._resolve(str(arguments["path"]))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(arguments["content"]), encoding="utf-8")
        except Exception as exc:
            return ToolResult(call_id=call_id, content=f"write_file error: {exc}", is_error=True)
        return ToolResult(call_id=call_id, content=f"wrote {path}")


class FinishTool:
    """Explicit task-completion signal (like OpenHands' finish action).

    The reference loop treats a STOP finish reason as terminal, but a `finish`
    tool gives the model an explicit way to end while returning a summary.
    """

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="finish",
            description="Signal that the task is complete. Provide a final summary.",
            parameters={"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]},
            writes=False,
        )

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        call_id = str(arguments.get("__call_id__", ""))
        return ToolResult(call_id=call_id, content=str(arguments.get("summary", "done")))


def default_tools(workspace: str | Path = ".") -> list:
    return [
        ReadFileTool(workspace),
        ListDirTool(workspace),
        WriteFileTool(workspace),
        FinishTool(),
    ]
