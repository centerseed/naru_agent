from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from naru_agent.streaming import StreamChunk


class BaseLLM(ABC):
    """Abstract LLM interface. All providers implement this."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict] | None = None,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> LLMResponse:
        ...

    @abstractmethod
    def chat_structured(
        self,
        messages: list[dict[str, str]],
        response_schema: type,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> Any:
        """Return a parsed object matching response_schema (a Pydantic model)."""
        ...

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        tools: list[dict] | None = None,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Async streaming chat. Override in subclasses that support streaming."""
        raise NotImplementedError(f"{type(self).__name__} does not support streaming")
        # Make this an async generator
        yield  # type: ignore[misc]  # pragma: no cover


class LLMResponse:
    """Unified response from any LLM provider."""

    def __init__(
        self,
        content: str | None = None,
        tool_calls: list[dict] | None = None,
        raw: Any = None,
        usage: dict | None = None,
    ):
        self.content = content
        self.tool_calls = tool_calls or []
        self.raw = raw
        self.usage = usage or {}

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0
