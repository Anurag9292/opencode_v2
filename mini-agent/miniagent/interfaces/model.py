from typing import AsyncIterator, Protocol

from ..types import ModelContext, ModelEvent, ToolSpec


class ModelProvider(Protocol):
    """Adapter for one LLM API.

    The whole point of this seam is the *normalized event stream*: whatever
    the provider's wire format (Anthropic, OpenAI, a local model), stream()
    yields the same three events -- TextDelta, ToolCallRequest, Finish --
    so the AgentLoop never contains provider-specific code.

    Contract:
    - exactly one model call per invocation (one "provider turn")
    - the final event must be a Finish with a normalized reason
    - tool call arguments are fully parsed dicts by the time they're yielded
    """

    def stream(
        self,
        context: ModelContext,
        tools: list[ToolSpec],
    ) -> AsyncIterator[ModelEvent]: ...
