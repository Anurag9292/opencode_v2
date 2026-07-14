from typing import Any, Protocol

from ..types import ToolContext, ToolResult, ToolSpec


class Tool(Protocol):
    """One capability the model may invoke.

    - spec() is what the model sees (name, description, JSON-schema args).
      The description is prompt engineering; treat it as such.
    - execute() performs the side effect. It must call ctx.ask() before
      doing anything irreversible, and should return model-readable text
      (errors included -- a caught error string the model can react to is
      more useful than an exception that kills the turn).
    """

    def spec(self) -> ToolSpec: ...

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult: ...


class ToolRegistry(Protocol):
    """Assembles the toolset offered to the model for a session.

    A seam rather than a plain dict because production harnesses filter
    tools per agent/mode, merge in external sources (MCP), and rename
    on collision. Version one just wraps a dict.
    """

    def specs(self) -> list[ToolSpec]: ...

    def get(self, name: str) -> Tool | None: ...
