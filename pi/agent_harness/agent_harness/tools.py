"""Tool interface, argument validation, ToolRegistry, and a few built-in tools.

pi origin:
  - `Tool` mirrors `AgentTool` (packages/agent/src/types.ts): name, description,
    JSON-schema `parameters`, and `execute(id, args, on_update)`.
  - `ToolRegistry` mirrors AgentSession's `_toolRegistry` map
    (packages/coding-agent/src/core/agent-session.ts).
  - Built-in tools mirror packages/coding-agent/src/core/tools/{read,write,ls,bash}.ts,
    reduced to safe, minimal implementations.
  - `validate_arguments` mirrors `validateToolArguments`
    (packages/ai/src/utils/validation.ts), reduced to required-key + basic type checks.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from .types import ToolCall, ToolResult

# Callback a tool may call to stream progress. pi origin: `onUpdate` in AgentTool.execute.
OnUpdate = Callable[[ToolResult], None]


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema (object)

    def execute(self, tool_call_id: str, args: dict[str, Any], on_update: OnUpdate) -> ToolResult: ...


class ToolValidationError(Exception):
    """Raised when tool arguments do not satisfy the schema."""


def validate_arguments(tool: Tool, args: dict[str, Any]) -> dict[str, Any]:
    """Minimal JSON-schema validation: required keys present + primitive types.

    pi uses TypeBox/JSON-schema compilation; here we check `required` and the
    declared primitive `type` of each property. Unknown keys are allowed.
    """

    schema = tool.parameters or {}
    props: dict[str, Any] = schema.get("properties", {})
    required: list[str] = schema.get("required", [])

    for key in required:
        if key not in args:
            raise ToolValidationError(f"Missing required argument '{key}' for tool '{tool.name}'")

    type_map = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}
    for key, value in args.items():
        declared = props.get(key, {}).get("type")
        expected = type_map.get(declared) if declared else None
        if expected and not isinstance(value, expected):
            raise ToolValidationError(
                f"Argument '{key}' for tool '{tool.name}' must be {declared}, got {type(value).__name__}"
            )
    return args


class ToolRegistry:
    """Holds the active tools and exposes their schemas for the context builder."""

    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in self._tools.values()
        ]


# ---------------------------------------------------------------------------
# Built-in tools (cwd-scoped, minimal).
# ---------------------------------------------------------------------------


@dataclass
class ReadFileTool:
    name: str = "read_file"
    description: str = "Read a UTF-8 text file relative to the working directory."
    cwd: str = "."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path"}},
            "required": ["path"],
        }

    def execute(self, tool_call_id: str, args: dict[str, Any], on_update: OnUpdate) -> ToolResult:
        path = Path(self.cwd) / args["path"]
        on_update(ToolResult(content=f"Reading {path}..."))
        text = path.read_text(encoding="utf-8")
        return ToolResult(content=text, details={"path": str(path), "bytes": len(text)})


@dataclass
class WriteFileTool:
    name: str = "write_file"
    description: str = "Write UTF-8 text to a file relative to the working directory."
    cwd: str = "."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        }

    def execute(self, tool_call_id: str, args: dict[str, Any], on_update: OnUpdate) -> ToolResult:
        path = Path(self.cwd) / args["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"], encoding="utf-8")
        return ToolResult(content=f"Wrote {len(args['content'])} bytes to {path}", details={"path": str(path)})


@dataclass
class ListDirTool:
    name: str = "list_dir"
    description: str = "List entries in a directory relative to the working directory."
    cwd: str = "."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": [],
        }

    def execute(self, tool_call_id: str, args: dict[str, Any], on_update: OnUpdate) -> ToolResult:
        path = Path(self.cwd) / args.get("path", ".")
        entries = sorted(os.listdir(path))
        return ToolResult(content="\n".join(entries), details={"path": str(path), "count": len(entries)})


@dataclass
class BashTool:
    """Runs a shell command. Intended to be gated by a PermissionPolicy."""

    name: str = "bash"
    description: str = "Run a shell command and return its combined output."
    cwd: str = "."
    timeout: int = 30

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        }

    def execute(self, tool_call_id: str, args: dict[str, Any], on_update: OnUpdate) -> ToolResult:
        proc = subprocess.run(
            args["command"],
            shell=True,
            cwd=self.cwd,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        return ToolResult(
            content=output.strip() or "(no output)",
            details={"exit_code": proc.returncode},
            is_error=proc.returncode != 0,
        )


def default_tools(cwd: str = ".") -> list[Tool]:
    """The default read/write/list/bash set (pi default is read/bash/edit/write)."""

    return [ReadFileTool(cwd=cwd), WriteFileTool(cwd=cwd), ListDirTool(cwd=cwd), BashTool(cwd=cwd)]
