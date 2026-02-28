from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any

from naru_agent.agent import Agent
from naru_agent.events import EventBus
from naru_agent.llm.base import LLMResponse
from naru_agent.streaming import (
    DoneEvent,
    ErrorEvent,
    StreamEvent,
    TextDeltaEvent,
    ToolCallStartEvent,
    ToolResultEvent,
    _accumulate_tool_call_chunks,
    _finalize_tool_calls,
)
from naru_agent.tool_selection.base import BaseToolSelector

if TYPE_CHECKING:
    from naru_agent.session.base import BaseSessionStore

logger = logging.getLogger(__name__)


class Runner:
    """Executes an agent's ReAct loop: think → tool call → observe → repeat.

    Usage:
        runner = Runner(agent)
        response = runner.run(user_id="user_123", message="推薦膝蓋友善的訓練")
    """

    def __init__(
        self,
        agent: Agent,
        event_bus: EventBus | None = None,
        tool_selector: BaseToolSelector | None = None,
    ):
        self.agent = agent
        self.events = event_bus or EventBus()
        self.tool_selector = tool_selector

    # ------------------------------------------------------------------
    # Sync run (backward compatible, now with parallel tool execution)
    # ------------------------------------------------------------------

    def run(
        self,
        message: str,
        user_id: str | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> RunResult:
        # 1. Input guardrails
        for guard in self.agent.guardrails:
            result = guard.check_input(message)
            if not result.passed:
                return RunResult(
                    content=result.modified_text or "Request blocked.",
                    blocked=True,
                    reason=result.reason,
                )

        # 2. Build messages
        memory_context = ""
        if self.agent.memory and user_id:
            memory_context = self.agent.memory.get_context_string(user_id, message)

        system_msg = self.agent.get_system_message(memory_context)
        messages: list[dict[str, str]] = [{"role": "system", "content": system_msg}]

        if conversation_history:
            messages.extend(conversation_history)

        messages.append({"role": "user", "content": message})

        # 3. ReAct loop
        all_tool_schemas = self.agent.get_tool_schemas() if self.agent.tools else None
        total_usage: dict[str, int] = {}
        used_tool_names: set[str] = set()

        for iteration in range(self.agent.max_iterations):
            tools = self._select_tools_for_iteration(
                messages, all_tool_schemas, used_tool_names,
            )

            self.events.emit("before_llm_call", {
                "iteration": iteration,
                "message_count": len(messages),
            })

            response = self.agent.llm.chat(messages=messages, tools=tools)
            self._accumulate_usage(total_usage, response.usage)

            self.events.emit("after_llm_call", {
                "iteration": iteration,
                "has_tool_calls": response.has_tool_calls,
            })

            if not response.has_tool_calls:
                # Done — final text response
                final_content = response.content or ""

                # 4. Output guardrails
                for guard in self.agent.guardrails:
                    result = guard.check_output(final_content)
                    if not result.passed:
                        final_content = result.modified_text or final_content

                # 5. Save to memory (non-blocking in future)
                if self.agent.memory and user_id:
                    all_msgs = list(conversation_history) if conversation_history else []
                    all_msgs.append({"role": "user", "content": message})
                    all_msgs.append({"role": "assistant", "content": final_content})
                    try:
                        self.agent.memory.add(user_id, all_msgs)
                    except Exception:
                        logger.exception("Failed to save memory")

                return RunResult(content=final_content, usage=total_usage)

            # Execute tool calls — build assistant message
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"]),
                        },
                    }
                    for tc in response.tool_calls
                ],
            }
            if response.content is not None:
                assistant_msg["content"] = response.content
            messages.append(assistant_msg)

            # Parallel tool execution
            for tc in response.tool_calls:
                used_tool_names.add(tc["name"])

            results: dict[str, str] = {}
            with ThreadPoolExecutor() as executor:
                futures = {
                    executor.submit(self._execute_tool_sync, tc): tc
                    for tc in response.tool_calls
                }
                for future in as_completed(futures):
                    tc = futures[future]
                    try:
                        tool_result = future.result()
                    except Exception as e:
                        logger.exception("Unexpected error in tool execution for %s", tc["name"])
                        tool_result = f"Error: {e}"
                    results[tc["id"]] = tool_result

            # Append in original order (LLM API requires it)
            for tc in response.tool_calls:
                tool_result = results[tc["id"]]

                self.events.emit("after_tool_call", {
                    "tool": tc["name"],
                    "result_length": len(tool_result),
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_result,
                })

        return RunResult(
            content="Max iterations reached.",
            usage=total_usage,
        )

    # ------------------------------------------------------------------
    # Async streaming run
    # ------------------------------------------------------------------

    async def run_stream(
        self,
        message: str,
        user_id: str | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        session_id: str | None = None,
        session_store: BaseSessionStore | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        # 1. Input guardrails
        for guard in self.agent.guardrails:
            result = guard.check_input(message)
            if not result.passed:
                yield ErrorEvent(error=result.reason or "Request blocked.")
                return

        # 2. Load session history if provided
        session_history: list[dict] | None = None
        if session_id and session_store:
            try:
                session_history = await session_store.get(session_id)
            except Exception:
                logger.exception("Failed to load session '%s'", session_id)

        # 3. Build messages
        memory_context = ""
        if self.agent.memory and user_id:
            memory_context = self.agent.memory.get_context_string(user_id, message)

        system_msg = self.agent.get_system_message(memory_context)
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_msg}]

        if session_history is not None:
            messages.extend(session_history)
        elif conversation_history:
            messages.extend(conversation_history)

        messages.append({"role": "user", "content": message})

        # 4. ReAct loop
        all_tool_schemas = self.agent.get_tool_schemas() if self.agent.tools else None
        total_usage: dict[str, int] = {}
        used_tool_names: set[str] = set()

        for iteration in range(self.agent.max_iterations):
            tools = self._select_tools_for_iteration(
                messages, all_tool_schemas, used_tool_names,
            )

            # Stream LLM response
            text_snapshot = ""
            accumulated_tc_chunks: dict[int, dict] = {}
            finish_reason = None

            async for chunk in self.agent.llm.chat_stream(messages=messages, tools=tools):
                # Text deltas
                if chunk.delta_text:
                    text_snapshot += chunk.delta_text
                    yield TextDeltaEvent(delta=chunk.delta_text, snapshot=text_snapshot)

                # Tool call deltas
                if chunk.tool_call_deltas:
                    _accumulate_tool_call_chunks(accumulated_tc_chunks, chunk.tool_call_deltas)

                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason

                if chunk.usage:
                    self._accumulate_usage(total_usage, chunk.usage)

            # Handle final response
            if finish_reason != "tool_calls" or not accumulated_tc_chunks:
                # Done — text response
                final_content = text_snapshot

                # Output guardrails
                for guard in self.agent.guardrails:
                    result = guard.check_output(final_content)
                    if not result.passed:
                        final_content = result.modified_text or final_content

                # Save session
                if session_id and session_store:
                    try:
                        conv_msgs = [m for m in messages[1:]]
                        conv_msgs.append({"role": "assistant", "content": final_content})
                        await session_store.save(session_id, conv_msgs)
                    except Exception:
                        logger.exception("Failed to save session '%s'", session_id)

                yield DoneEvent(content=final_content, usage=total_usage)
                return

            # Tool calls
            tool_calls = _finalize_tool_calls(accumulated_tc_chunks)

            # Build assistant message
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"]),
                        },
                    }
                    for tc in tool_calls
                ],
            }
            if text_snapshot:
                assistant_msg["content"] = text_snapshot
            messages.append(assistant_msg)

            # Yield start events
            for tc in tool_calls:
                used_tool_names.add(tc["name"])
                yield ToolCallStartEvent(
                    tool_call_id=tc["id"],
                    name=tc["name"],
                    arguments=tc["arguments"],
                )

            # Parallel async tool execution
            tasks = [self._execute_tool_async(tc) for tc in tool_calls]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Handle any unexpected exceptions from gather
            resolved_results = []
            for i, result in enumerate(results):
                if isinstance(result, BaseException):
                    tc = tool_calls[i]
                    logger.exception(
                        "Unexpected error in async tool execution for %s",
                        tc["name"], exc_info=result,
                    )
                    resolved_results.append((tc, f"Error: {result}"))
                else:
                    resolved_results.append(result)
            results = resolved_results

            # Append results in order and yield events
            results_by_id = {tc["id"]: (tc, res) for tc, res in results}
            for tc in tool_calls:
                _, tool_result = results_by_id[tc["id"]]

                yield ToolResultEvent(
                    tool_call_id=tc["id"],
                    name=tc["name"],
                    result=tool_result,
                )

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_result,
                })

        # Max iterations
        if session_id and session_store:
            try:
                conv_msgs = [m for m in messages[1:]]
                await session_store.save(session_id, conv_msgs)
            except Exception:
                logger.exception("Failed to save session '%s' on max iterations", session_id)

        yield ErrorEvent(error="Max iterations reached.")

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    async def _execute_tool_async(self, tc: dict) -> tuple[dict, str]:
        """Execute a single tool call asynchronously."""
        self.events.emit("before_tool_call", {
            "tool": tc["name"],
            "arguments": tc["arguments"],
        })
        tool_obj = self.agent.get_tool_by_name(tc["name"])
        if tool_obj:
            try:
                result = await tool_obj.arun(**tc["arguments"])
            except Exception as e:
                result = f"Error: {e}"
        else:
            result = f"Error: Unknown tool '{tc['name']}'"
        self.events.emit("after_tool_call", {
            "tool": tc["name"],
            "result_length": len(result),
        })
        return tc, result

    def _execute_tool_sync(self, tc: dict) -> str:
        """Execute a single tool call synchronously."""
        self.events.emit("before_tool_call", {
            "tool": tc["name"],
            "arguments": tc["arguments"],
        })

        tool_obj = self.agent.get_tool_by_name(tc["name"])
        if tool_obj:
            try:
                return tool_obj.run(**tc["arguments"])
            except Exception as e:
                return f"Error: {e}"
        return f"Error: Unknown tool '{tc['name']}'"

    def _select_tools_for_iteration(
        self,
        messages: list[dict],
        all_tool_schemas: list[dict] | None,
        used_tool_names: set[str],
    ) -> list[dict] | None:
        if all_tool_schemas is None or self.tool_selector is None:
            return all_tool_schemas

        # Build query from recent messages
        query_parts: list[str] = []
        for msg in reversed(messages):
            if msg["role"] in ("user", "tool"):
                content = msg.get("content", "")
                query_parts.append(content[:200])
                if msg["role"] == "user":
                    break
        query = " ".join(reversed(query_parts))

        result = self.tool_selector.select_tools(
            tools=self.agent.tools,
            query=query,
            context=messages,
            used_tool_names=used_tool_names,
        )

        self.events.emit("tool_selection", {
            "total_tools": len(result.all_tools),
            "selected_tools": len(result.selected_tools),
            "was_filtered": result.was_filtered,
            "selected_names": [t.name for t in result.selected_tools],
            "scores": result.scores,
        })

        if not result.was_filtered:
            return all_tool_schemas

        return [t.to_schema() for t in result.selected_tools]

    @staticmethod
    def _accumulate_usage(total: dict, usage: dict) -> None:
        for key, value in usage.items():
            if isinstance(value, (int, float)):
                total[key] = total.get(key, 0) + value
            elif isinstance(value, dict):
                if key not in total:
                    total[key] = {}
                Runner._accumulate_usage(total[key], value)


class RunResult:
    def __init__(
        self,
        content: str,
        blocked: bool = False,
        reason: str | None = None,
        usage: dict | None = None,
    ):
        self.content = content
        self.blocked = blocked
        self.reason = reason
        self.usage = usage or {}
