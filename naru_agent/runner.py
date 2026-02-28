from __future__ import annotations

import json
import logging
from typing import Any

from naru_agent.agent import Agent
from naru_agent.events import EventBus
from naru_agent.llm.base import LLMResponse
from naru_agent.tool_selection.base import BaseToolSelector

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

            # Execute tool calls
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

            for tc in response.tool_calls:
                used_tool_names.add(tc["name"])
                self.events.emit("before_tool_call", {
                    "tool": tc["name"],
                    "arguments": tc["arguments"],
                })

                tool_obj = self.agent.get_tool_by_name(tc["name"])
                if tool_obj:
                    try:
                        tool_result = tool_obj.run(**tc["arguments"])
                    except Exception as e:
                        tool_result = f"Error: {e}"
                else:
                    tool_result = f"Error: Unknown tool '{tc['name']}'"

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
