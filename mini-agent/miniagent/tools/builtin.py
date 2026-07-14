import os
from typing import Any

from ..types import ToolContext, ToolResult, ToolSpec

MAX_OUTPUT = 30_000  # characters; protects the context window from huge files


def safe_path(workdir: str, relative: str) -> str:
    """Resolve a path and refuse to escape the workspace."""
    resolved = os.path.realpath(os.path.join(workdir, relative))
    if not (resolved + os.sep).startswith(os.path.realpath(workdir) + os.sep) and resolved != os.path.realpath(workdir):
        raise ValueError(f"path escapes workspace: {relative}")
    return resolved


def truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    return text[:MAX_OUTPUT] + f"\n... (truncated, {len(text) - MAX_OUTPUT} more characters)"


class ReadTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="read",
            description=(
                "Read a text file from the workspace. Returns the content with "
                "line numbers. Always read a file before editing it."
            ),
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Path relative to the workspace root"}},
                "required": ["path"],
            },
        )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        # Reading is side-effect free inside the workspace: no permission ask.
        path = safe_path(ctx.workdir, args["path"])
        with open(path) as f:
            lines = f.readlines()
        numbered = "".join(f"{i + 1}: {line}" for i, line in enumerate(lines))
        return ToolResult(output=truncate(numbered), title=args["path"])


class WriteTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="write",
            description="Create or overwrite a text file in the workspace with the given content.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the workspace root"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        from ..types import PermissionRequest

        path = safe_path(ctx.workdir, args["path"])
        ctx.ask(PermissionRequest(
            session_id=ctx.session_id, tool="write", action="write", pattern=args["path"],
        ))
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            f.write(args["content"])
        return ToolResult(output=f"wrote {len(args['content'])} bytes to {args['path']}", title=args["path"])


class ListTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="list",
            description="List files and directories at a path in the workspace (non-recursive).",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Path relative to the workspace root, defaults to '.'"}},
                "required": [],
            },
        )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = safe_path(ctx.workdir, args.get("path", "."))
        entries = sorted(
            name + ("/" if os.path.isdir(os.path.join(path, name)) else "")
            for name in os.listdir(path)
        )
        return ToolResult(output=truncate("\n".join(entries) or "(empty)"), title=args.get("path", "."))


class BashTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="bash",
            description=(
                "Run a shell command in the workspace and return stdout+stderr. "
                "Use for builds, tests, git, and anything the other tools cannot do."
            ),
            parameters={
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        import asyncio

        from ..types import PermissionRequest

        ctx.ask(PermissionRequest(
            session_id=ctx.session_id, tool="bash", action="bash", pattern=args["command"],
        ))
        process = await asyncio.create_subprocess_shell(
            args["command"],
            cwd=ctx.workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=120)
        output = stdout.decode(errors="replace")
        if process.returncode != 0:
            output += f"\n(exit code {process.returncode})"
        return ToolResult(output=truncate(output) or "(no output)", title=args["command"])


def default_tools() -> list:
    return [ReadTool(), WriteTool(), ListTool(), BashTool()]
