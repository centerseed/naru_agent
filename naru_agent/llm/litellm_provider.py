from __future__ import annotations

import json
import logging
from typing import Any

import litellm

from naru_agent.llm.base import BaseLLM, LLMResponse

logger = logging.getLogger(__name__)


class LiteLLMProvider(BaseLLM):
    """LLM provider via LiteLLM — supports 100+ models with a unified interface."""

    def __init__(
        self,
        model: str = "gemini/gemini-2.5-flash-lite",
        api_key: str | None = None,
        api_base: str | None = None,
        default_temperature: float = 0.3,
        **extra: Any,
    ):
        self.model = model
        self.api_key = api_key
        self.api_base = api_base
        self.default_temperature = default_temperature
        self.extra = extra

    def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        params: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature or self.default_temperature,
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
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
        )

    def chat_structured(
        self,
        messages: list[dict[str, str]],
        response_schema: type,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> Any:
        """Use response_format for structured output, then parse with Pydantic."""
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
        content = response.choices[0].message.content
        return response_schema.model_validate_json(content)
