"""Tests for parallel tool execution in Runner.run() (sync path)."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

from naru_agent.agent import Agent
from naru_agent.events import EventBus
from naru_agent.llm.base import LLMResponse
from naru_agent.runner import Runner
from naru_agent.tools.base import FunctionTool

from tests.conftest import MockLLM


def _make_agent(llm, tools=None, max_iterations=10):
    return Agent(
        name="test",
        role="assistant",
        llm=llm,
        tools=tools or [],
        max_iterations=max_iterations,
    )


class TestParallelToolExecution:
    def test_two_tools_run_in_parallel(self, mock_llm: MockLLM):
        """Verify tools actually run in parallel by checking thread IDs differ."""
        thread_ids = []

        def tool_a() -> str:
            thread_ids.append(("a", threading.current_thread().ident))
            time.sleep(0.1)
            return "result_a"

        def tool_b() -> str:
            thread_ids.append(("b", threading.current_thread().ident))
            time.sleep(0.1)
            return "result_b"

        ta = FunctionTool(tool_a, name="tool_a", description="A")
        tb = FunctionTool(tool_b, name="tool_b", description="B")

        mock_llm.queue_responses([
            LLMResponse(
                tool_calls=[
                    {"id": "tc_a", "name": "tool_a", "arguments": {}},
                    {"id": "tc_b", "name": "tool_b", "arguments": {}},
                ],
                usage={"prompt_tokens": 10, "completion_tokens": 5},
            ),
            LLMResponse(content="Done", usage={"prompt_tokens": 5, "completion_tokens": 3}),
        ])

        agent = _make_agent(mock_llm, tools=[ta, tb])
        runner = Runner(agent)

        start = time.time()
        result = runner.run("run both")
        elapsed = time.time() - start

        assert result.content == "Done"
        # If truly parallel, should be ~0.1s not ~0.2s
        assert elapsed < 0.18, f"Expected parallel execution but took {elapsed:.2f}s"

        # Both tools ran in different threads
        assert len(thread_ids) == 2
        a_tid = next(tid for name, tid in thread_ids if name == "a")
        b_tid = next(tid for name, tid in thread_ids if name == "b")
        assert a_tid != b_tid

    def test_results_in_original_order(self, mock_llm: MockLLM):
        """Tool results must be appended in the order LLM returned them."""
        def fast() -> str:
            return "fast_result"

        def slow() -> str:
            time.sleep(0.05)
            return "slow_result"

        t_slow = FunctionTool(slow, name="slow", description="Slow")
        t_fast = FunctionTool(fast, name="fast", description="Fast")

        # slow comes first in tool_calls
        mock_llm.queue_responses([
            LLMResponse(
                tool_calls=[
                    {"id": "tc_slow", "name": "slow", "arguments": {}},
                    {"id": "tc_fast", "name": "fast", "arguments": {}},
                ],
                usage={},
            ),
            LLMResponse(content="ok", usage={}),
        ])

        agent = _make_agent(mock_llm, tools=[t_slow, t_fast])
        runner = Runner(agent)
        result = runner.run("test")

        # Check messages order in the second LLM call
        second_call_msgs = mock_llm.chat_calls[1]["messages"]
        tool_msgs = [m for m in second_call_msgs if m.get("role") == "tool"]

        assert tool_msgs[0]["tool_call_id"] == "tc_slow"
        assert tool_msgs[0]["content"] == "slow_result"
        assert tool_msgs[1]["tool_call_id"] == "tc_fast"
        assert tool_msgs[1]["content"] == "fast_result"

    def test_single_tool_not_affected(self, mock_llm: MockLLM):
        def single_tool(x: int) -> str:
            return str(x * 2)

        tool = FunctionTool(single_tool, name="double", description="Double")

        mock_llm.queue_responses([
            LLMResponse(
                tool_calls=[{"id": "tc_1", "name": "double", "arguments": {"x": 5}}],
                usage={},
            ),
            LLMResponse(content="10", usage={}),
        ])

        agent = _make_agent(mock_llm, tools=[tool])
        runner = Runner(agent)
        result = runner.run("double 5")

        assert result.content == "10"

    def test_tool_error_does_not_affect_others(self, mock_llm: MockLLM):
        def good() -> str:
            return "ok"

        def bad() -> str:
            raise ValueError("boom")

        t_good = FunctionTool(good, name="good", description="Good")
        t_bad = FunctionTool(bad, name="bad", description="Bad")

        mock_llm.queue_responses([
            LLMResponse(
                tool_calls=[
                    {"id": "tc_good", "name": "good", "arguments": {}},
                    {"id": "tc_bad", "name": "bad", "arguments": {}},
                ],
                usage={},
            ),
            LLMResponse(content="handled", usage={}),
        ])

        agent = _make_agent(mock_llm, tools=[t_good, t_bad])
        runner = Runner(agent)
        result = runner.run("test")

        assert result.content == "handled"

        # Verify messages: good succeeded, bad has error
        second_call_msgs = mock_llm.chat_calls[1]["messages"]
        tool_msgs = [m for m in second_call_msgs if m.get("role") == "tool"]

        good_msg = next(m for m in tool_msgs if m["tool_call_id"] == "tc_good")
        bad_msg = next(m for m in tool_msgs if m["tool_call_id"] == "tc_bad")

        assert good_msg["content"] == "ok"
        assert "Error" in bad_msg["content"]


# ---------------------------------------------------------------------------
# Edge-case tests
# ---------------------------------------------------------------------------

class TestParallelToolEdgeCases:
    """Fix #3: future.result() exception handling in sync parallel execution."""

    def test_unknown_tool_returns_error_string(self, mock_llm: MockLLM):
        """Calling a tool that doesn't exist should return an error, not crash."""
        mock_llm.queue_responses([
            LLMResponse(
                tool_calls=[{"id": "tc_1", "name": "nonexistent", "arguments": {}}],
                usage={},
            ),
            LLMResponse(content="handled", usage={}),
        ])

        agent = _make_agent(mock_llm, tools=[])
        runner = Runner(agent)
        result = runner.run("test")

        assert result.content == "handled"
        second_call_msgs = mock_llm.chat_calls[1]["messages"]
        tool_msgs = [m for m in second_call_msgs if m.get("role") == "tool"]
        assert "Error" in tool_msgs[0]["content"]
        assert "Unknown tool" in tool_msgs[0]["content"]

    def test_sync_emits_before_and_after_tool_events(self, mock_llm: MockLLM):
        """Sync run() should emit before_tool_call and after_tool_call events."""
        def my_tool() -> str:
            return "result"

        tool = FunctionTool(my_tool, name="my_tool", description="Test")
        emitted = []
        bus = EventBus()
        bus.on("before_tool_call", lambda data: emitted.append(("before", data)))
        bus.on("after_tool_call", lambda data: emitted.append(("after", data)))

        mock_llm.queue_responses([
            LLMResponse(
                tool_calls=[{"id": "tc_1", "name": "my_tool", "arguments": {}}],
                usage={},
            ),
            LLMResponse(content="done", usage={}),
        ])

        agent = _make_agent(mock_llm, tools=[tool])
        runner = Runner(agent, event_bus=bus)
        runner.run("test")

        before = [e for e in emitted if e[0] == "before"]
        after = [e for e in emitted if e[0] == "after"]
        assert len(before) == 1
        assert len(after) == 1
        assert before[0][1]["tool"] == "my_tool"
        assert after[0][1]["result_length"] == len("result")
