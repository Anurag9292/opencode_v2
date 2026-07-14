"""Tool and ToolRegistry.

A Tool is a single capability the agent can invoke (read a file, run a command,
finish the task). The ToolRegistry advertises specs to the model and dispatches
calls by name. In OpenHands these come from ``openhands.tools`` and are attached
to the agent (docs Step 4, [EXTERNAL]); here they are local and explicit.

Tool contract:
- ``spec`` describes the tool to the model (name/description/params/writes)
- ``run(arguments)`` executes and returns a ToolResult
- a tool MUST NOT raise for expected failures: it returns
  ``ToolResult(is_error=True, ...)`` so a bad call becomes an observation the
  model can recover from, not a loop crash.

Registry contract:
- ``specs()`` returns every advertised ToolSpec
- ``get(name)`` returns the tool or None (None -> the loop synthesizes an error
  observation for an unknown tool)
"""

from __future__ import annotations

from typing import Any, Protocol

from ..types import ToolResult, ToolSpec


class Tool(Protocol):
    @property
    def spec(self) -> ToolSpec: ...

    def run(self, arguments: dict[str, Any]) -> ToolResult: ...


class ToolRegistry(Protocol):
    def register(self, tool: Tool) -> None: ...

    def specs(self) -> list[ToolSpec]: ...

    def get(self, name: str) -> Tool | None: ...
