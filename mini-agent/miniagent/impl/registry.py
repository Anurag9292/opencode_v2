from ..interfaces.tool import Tool
from ..types import ToolSpec


class DictToolRegistry:
    """The simplest registry: a name -> Tool dict with collision checks."""

    def __init__(self, tools: list[Tool]) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            name = tool.spec().name
            if name in self._tools:
                raise ValueError(f"duplicate tool name: {name}")
            self._tools[name] = tool

    def specs(self) -> list[ToolSpec]:
        return [tool.spec() for tool in self._tools.values()]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)
