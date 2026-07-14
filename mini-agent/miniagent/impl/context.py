import os
import platform
import time

from ..types import Message, ModelContext

BASE_PROMPT = """\
You are a coding agent operating inside a workspace directory.
Work step by step: inspect files before editing, prefer small verifiable
changes, and use the provided tools for every filesystem or shell action.
When the task is complete, reply with a short summary and stop calling tools.
"""


class SimpleContextBuilder:
    """System prompt = base instructions + environment + project AGENTS.md.

    History passes through untouched in v1 -- no truncation, no compaction.
    This is the file to grow when context gets smarter.
    """

    def __init__(self, workdir: str) -> None:
        self.workdir = workdir

    def build(self, session_id: str, history: list[Message]) -> ModelContext:
        sections = [BASE_PROMPT, self._environment()]
        instructions = self._project_instructions()
        if instructions:
            sections.append(f"Project instructions (AGENTS.md):\n{instructions}")
        return ModelContext(system="\n\n".join(sections), messages=history)

    def _environment(self) -> str:
        return (
            "Environment:\n"
            f"  working directory: {self.workdir}\n"
            f"  platform: {platform.system().lower()}\n"
            f"  date: {time.strftime('%Y-%m-%d')}"
        )

    def _project_instructions(self) -> str:
        path = os.path.join(self.workdir, "AGENTS.md")
        if not os.path.exists(path):
            return ""
        with open(path) as f:
            return f.read().strip()
