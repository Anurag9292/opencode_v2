"""SystemPromptContextBuilder — builds the messages sent to the model.

This is where the "system prompt construction" + "instruction loading" of the
architecture docs happen (Steps 3-4). It:

1. renders a system message from a persona template + the advertised tool list
   + any loaded instruction fragments ("skills"),
2. applies a simple context-window budget by keeping the most recent messages
   (a stand-in for OpenHands' condenser),
3. returns the exact ``list[Message]`` the loop passes to ``model.complete``.

The default template is inline and inspectable; a real harness would render a
file template and inject repo-specific instructions here.
"""

from __future__ import annotations

from ..interfaces.tool import ToolRegistry
from ..types import Message

_DEFAULT_PERSONA = (
    "You are a minimal coding agent. You solve the user's task by thinking, "
    "then either calling a tool or giving a final answer. "
    "Only use the tools listed below. When the task is done, call `finish`."
)


class SystemPromptContextBuilder:
    def __init__(
        self,
        registry: ToolRegistry,
        persona: str = _DEFAULT_PERSONA,
        instructions: list[str] | None = None,
        max_history: int = 50,
    ) -> None:
        self.registry = registry
        self.persona = persona
        # "skills"/microagents: extra instruction fragments merged into the prompt
        self.instructions = list(instructions or [])
        self.max_history = max_history

    def add_instruction(self, text: str) -> None:
        """Load an instruction fragment (the harness analogue of a skill)."""
        self.instructions.append(text)

    def build(self, session_id: str, history: list[Message]) -> list[Message]:
        system = Message(role="system", content=self._render_system())
        budgeted = history[-self.max_history :] if self.max_history else history
        return [system, *budgeted]

    def _render_system(self) -> str:
        lines = [self.persona, "", "# Available tools"]
        for spec in self.registry.specs():
            required = ", ".join(spec.parameters.get("required", [])) or "none"
            flag = " (writes)" if spec.writes else ""
            lines.append(f"- {spec.name}{flag}: {spec.description} [args: {required}]")
        if self.instructions:
            lines += ["", "# Instructions"]
            lines += [f"- {i}" for i in self.instructions]
        return "\n".join(lines)
