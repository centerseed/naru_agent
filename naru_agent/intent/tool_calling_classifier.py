"""Tool calling classifier — lightweight LLM call with tool schemas."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from naru_agent.llm.litellm_provider import LiteLLMProvider
from naru_agent.tools.base import BaseTool

logger = logging.getLogger(__name__)


@dataclass
class ToolCallingResult:
    """Result of tool calling classification.

    Attributes:
        tool_results: List of tool call results, each with tool name, args, and result.
        usage: Token usage from the classifier LLM call (keys: prompt_tokens,
            completion_tokens, total_tokens — matches LiteLLMProvider._extract_usage).
        raw_response: Raw LLM text content (if any).
    """

    tool_results: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    raw_response: str = ""


class BaseToolCallingClassifier(ABC):
    """Abstract interface for tool calling classification."""

    @abstractmethod
    def classify(self, message: str, tools: list[BaseTool]) -> ToolCallingResult:
        """Use a lightweight LLM to decide which tools to call, execute them,
        and return the results."""
        ...


class LLMToolCallingClassifier(BaseToolCallingClassifier):
    """Uses litellm.completion with tool schemas to let a lightweight model
    decide which tools to call, then executes them."""

    def __init__(
        self,
        model: str = "gemini/gemini-2.5-flash-lite",
        api_key: str | None = None,
        temperature: float = 0.0,
        system_prompt: str = (
            "You are a tool-calling assistant. "
            "Analyze the user's message and call the appropriate tools. "
            "If no tool is needed, respond with a short explanation."
        ),
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.system_prompt = system_prompt

    def classify(self, message: str, tools: list[BaseTool]) -> ToolCallingResult:
        """Classify and execute tool calls."""
        from naru_agent.llm.async_gateway import llm_gateway

        tool_schemas = [t.to_schema() for t in tools]
        tool_map = {t.name: t for t in tools}

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": message},
        ]

        try:
            # 走 gateway sync 入口:取得 fail-fast + Mistral fallback(此方法跑在 achat 的
            # to_thread 內,complete_sync 自持並發閘、不阻塞 event loop)。
            response = llm_gateway.complete_sync(
                messages,
                model=self.model,
                usage_type="tool_classifier",
                user_id="",
                timeout_s=15,
                tools=tool_schemas,
                temperature=self.temperature,
                api_key=self.api_key,
            )
        except Exception:
            logger.warning("Tool calling classifier LLM call failed", exc_info=True)
            return ToolCallingResult()

        usage: dict[str, Any] = {}
        if hasattr(response, "usage") and response.usage:
            usage = LiteLLMProvider._extract_usage(response.usage)

        choice = response.choices[0]
        raw_content = choice.message.content or ""
        tool_calls = getattr(choice.message, "tool_calls", None) or []

        if not tool_calls:
            return ToolCallingResult(usage=usage, raw_response=raw_content)

        # Parse all tool call arguments upfront
        parsed: list[tuple[str, dict, Any]] = []  # (name, args, tool_obj)
        for tc in tool_calls:
            fn = tc.function
            name = fn.name
            try:
                args = json.loads(fn.arguments) if fn.arguments else {}
            except (json.JSONDecodeError, TypeError):
                args = {}
            tool_obj = tool_map.get(name)
            if tool_obj is None:
                logger.warning("Tool '%s' not found, skipping", name)
                continue
            parsed.append((name, args, tool_obj))

        if not parsed:
            return ToolCallingResult(usage=usage, raw_response=raw_content)

        # Execute tool calls in parallel
        results: list[dict] = [{}] * len(parsed)

        def _run(idx: int, name: str, args: dict, tool_obj: BaseTool) -> tuple[int, dict]:
            try:
                result = tool_obj.run(**args)
            except Exception:
                logger.warning("Tool '%s' execution failed", name, exc_info=True)
                result = f"Error executing tool {name}"
            return idx, {"tool": name, "args": args, "result": str(result)}

        with ThreadPoolExecutor(max_workers=len(parsed)) as executor:
            futures = {
                executor.submit(_run, i, name, args, tool_obj): i
                for i, (name, args, tool_obj) in enumerate(parsed)
            }
            for future in as_completed(futures):
                idx, entry = future.result()
                results[idx] = entry

        return ToolCallingResult(
            tool_results=results,
            usage=usage,
            raw_response=raw_content,
        )
