from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import litellm

from naru_agent.llm.base import BaseLLM, LLMResponse
from naru_agent.streaming import StreamChunk

logger = logging.getLogger(__name__)


class LiteLLMProvider(BaseLLM):
    """LLM provider via LiteLLM — supports 100+ models with a unified interface."""

    def __init__(
        self,
        model: str = "gemini/gemini-2.5-flash-lite",
        api_key: str | None = None,
        api_base: str | None = None,
        default_temperature: float = 0.3,
        enable_cache: bool = True,
        **extra: Any,
    ):
        self.model = model
        self.api_key = api_key
        self.api_base = api_base
        self.default_temperature = default_temperature
        self.enable_cache = enable_cache
        self.extra = extra

    @staticmethod
    def _apply_cache_control(messages: list[dict]) -> list[dict]:
        """Add cache_control to system messages, converting content to block format."""
        result = []
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                if isinstance(content, str):
                    content = [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
                elif isinstance(content, list):
                    content = [
                        {**block, "cache_control": {"type": "ephemeral"}} if block.get("type") == "text" else {**block}
                        for block in content
                    ]
                result.append({**msg, "content": content})
            else:
                result.append(msg)
        return result

    @staticmethod
    def _extract_usage(usage: Any) -> dict:
        """Extract usage dict including cache-related fields."""
        data: dict[str, Any] = {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        }
        if getattr(usage, "cache_creation_input_tokens", None) is not None:
            data["cache_creation_input_tokens"] = usage.cache_creation_input_tokens
        if getattr(usage, "cache_read_input_tokens", None) is not None:
            data["cache_read_input_tokens"] = usage.cache_read_input_tokens
        details = getattr(usage, "prompt_tokens_details", None)
        if details:
            detail_dict = details if isinstance(details, dict) else getattr(details, "__dict__", {})
            if detail_dict:
                data["prompt_tokens_details"] = {
                    k: v for k, v in detail_dict.items() if isinstance(v, (int, float))
                }
        return data

    _CACHE_SUPPORTED_PREFIXES = ("anthropic/", "claude-")

    def _should_apply_cache(self) -> bool:
        return self.enable_cache and self.model.startswith(self._CACHE_SUPPORTED_PREFIXES)

    def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        if self._should_apply_cache():
            messages = self._apply_cache_control(messages)

        params: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.default_temperature if temperature is None else temperature,
            **self.extra,
            **kwargs,
        }
        if self.api_key:
            params["api_key"] = self.api_key
        if self.api_base:
            params["api_base"] = self.api_base
        if tools:
            params["tools"] = tools

        response = litellm.completion(**params)
        if not response.choices:
            raise ValueError(
                f"LLM returned empty choices list (possible safety filter or high load). "
                f"Model: {self.model_id}"
            )
        choice = response.choices[0]
        message = choice.message

        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments),
                })

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            raw=response,
            usage=self._extract_usage(response.usage),
        )

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        if self._should_apply_cache():
            messages = self._apply_cache_control(messages)

        params: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.default_temperature if temperature is None else temperature,
            "stream": True,
            **self.extra,
            **kwargs,
        }
        if self.api_key:
            params["api_key"] = self.api_key
        if self.api_base:
            params["api_base"] = self.api_base
        if tools:
            params["tools"] = tools

        response = await litellm.acompletion(**params)

        async for chunk in response:
            choice = chunk.choices[0] if chunk.choices else None
            if choice is None:
                continue

            delta = choice.delta

            # Extract text delta
            delta_text = getattr(delta, "content", None)

            # Extract tool call deltas
            tool_call_deltas = []
            if getattr(delta, "tool_calls", None):
                for tc in delta.tool_calls:
                    tc_delta: dict[str, Any] = {"index": getattr(tc, "index", 0)}
                    if getattr(tc, "id", None):
                        tc_delta["id"] = tc.id
                    if getattr(tc, "function", None):
                        if getattr(tc.function, "name", None):
                            tc_delta["name"] = tc.function.name
                        if getattr(tc.function, "arguments", None):
                            tc_delta["arguments"] = tc.function.arguments
                    tool_call_deltas.append(tc_delta)

            # Extract usage from final chunk
            usage = None
            if getattr(chunk, "usage", None):
                usage = self._extract_usage(chunk.usage)

            yield StreamChunk(
                delta_text=delta_text,
                tool_call_deltas=tool_call_deltas,
                finish_reason=getattr(choice, "finish_reason", None),
                usage=usage,
            )

    def chat_structured(
        self,
        messages: list[dict[str, str]],
        response_schema: type,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> Any:
        """Use response_format for structured output, then parse with Pydantic."""
        if self._should_apply_cache():
            messages = self._apply_cache_control(messages)

        params: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            **self.extra,
            **kwargs,
        }
        if self.api_key:
            params["api_key"] = self.api_key
        if self.api_base:
            params["api_base"] = self.api_base

        response = litellm.completion(**params)
        if not response.choices:
            raise ValueError(
                f"LLM returned empty choices list (possible safety filter or high load). "
                f"Model: {self.model_id}"
            )
        content = response.choices[0].message.content
        return response_schema.model_validate_json(content)
