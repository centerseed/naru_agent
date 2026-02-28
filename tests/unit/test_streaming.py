"""Tests for Runner.run_stream() — streaming ReAct loop."""
from __future__ import annotations

import json
import logging

import pytest

from naru_agent.agent import Agent
from naru_agent.events import EventBus
from naru_agent.runner import Runner
from naru_agent.streaming import (
    DoneEvent,
    ErrorEvent,
    StreamChunk,
    TextDeltaEvent,
    ToolCallStartEvent,
    ToolResultEvent,
    _accumulate_tool_call_chunks,
    _finalize_tool_calls,
)
from naru_agent.tools.base import FunctionTool

# Import conftest fixtures
from tests.conftest import MockAsyncLLM


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(llm, tools=None, guardrails=None, max_iterations=10):
    return Agent(
        name="test",
        role="assistant",
        llm=llm,
        tools=tools or [],
        guardrails=guardrails or [],
        max_iterations=max_iterations,
    )


async def _collect_events(runner, message, **kwargs):
    events = []
    async for event in runner.run_stream(message, **kwargs):
        events.append(event)
    return events


# ---------------------------------------------------------------------------
# Tests — Happy path
# ---------------------------------------------------------------------------

class TestStreamingTextOnly:
    @pytest.mark.asyncio
    async def test_pure_text_stream(self, mock_async_llm: MockAsyncLLM):
        mock_async_llm.set_stream_text("Hello!")
        agent = _make_agent(mock_async_llm)
        runner = Runner(agent)

        events = await _collect_events(runner, "Hi")

        text_events = [e for e in events if isinstance(e, TextDeltaEvent)]
        done_events = [e for e in events if isinstance(e, DoneEvent)]

        assert len(text_events) == 6  # H, e, l, l, o, !
        assert text_events[-1].snapshot == "Hello!"
        assert len(done_events) == 1
        assert done_events[0].content == "Hello!"

    @pytest.mark.asyncio
    async def test_snapshot_accumulates_correctly(self, mock_async_llm: MockAsyncLLM):
        mock_async_llm.set_stream_text("AB")
        agent = _make_agent(mock_async_llm)
        runner = Runner(agent)

        events = await _collect_events(runner, "test")

        text_events = [e for e in events if isinstance(e, TextDeltaEvent)]
        assert text_events[0].delta == "A"
        assert text_events[0].snapshot == "A"
        assert text_events[1].delta == "B"
        assert text_events[1].snapshot == "AB"


class TestStreamingToolCalls:
    @pytest.mark.asyncio
    async def test_tool_call_stream(self, mock_async_llm: MockAsyncLLM):
        def greet(name: str) -> str:
            return f"Hi {name}!"

        tool = FunctionTool(greet, name="greet", description="Greet someone")
        mock_async_llm.set_stream_tool_call("greet", {"name": "World"}, final_text="Done")

        agent = _make_agent(mock_async_llm, tools=[tool])
        runner = Runner(agent)

        events = await _collect_events(runner, "Say hi to World")

        start_events = [e for e in events if isinstance(e, ToolCallStartEvent)]
        result_events = [e for e in events if isinstance(e, ToolResultEvent)]
        done_events = [e for e in events if isinstance(e, DoneEvent)]

        assert len(start_events) == 1
        assert start_events[0].name == "greet"
        assert start_events[0].arguments == {"name": "World"}

        assert len(result_events) == 1
        assert result_events[0].result == "Hi World!"

        assert len(done_events) == 1
        assert done_events[0].content == "Done"

    @pytest.mark.asyncio
    async def test_multi_tool_parallel_stream(self, mock_async_llm: MockAsyncLLM):
        def tool_a() -> str:
            return "result_a"

        def tool_b() -> str:
            return "result_b"

        ta = FunctionTool(tool_a, name="tool_a", description="Tool A")
        tb = FunctionTool(tool_b, name="tool_b", description="Tool B")

        # First stream: two tool calls
        args_a = json.dumps({})
        args_b = json.dumps({})
        tc_chunks = [
            StreamChunk(tool_call_deltas=[
                {"index": 0, "id": "tc_a", "name": "tool_a", "arguments": ""},
                {"index": 1, "id": "tc_b", "name": "tool_b", "arguments": ""},
            ]),
            StreamChunk(tool_call_deltas=[
                {"index": 0, "arguments": args_a},
                {"index": 1, "arguments": args_b},
            ]),
            StreamChunk(finish_reason="tool_calls", usage={"prompt_tokens": 10, "completion_tokens": 5}),
        ]
        mock_async_llm.queue_stream_sequence(tc_chunks)

        # Second stream: final text
        mock_async_llm.set_stream_text("All done")

        agent = _make_agent(mock_async_llm, tools=[ta, tb])
        runner = Runner(agent)

        events = await _collect_events(runner, "Run both")

        start_events = [e for e in events if isinstance(e, ToolCallStartEvent)]
        result_events = [e for e in events if isinstance(e, ToolResultEvent)]

        assert len(start_events) == 2
        assert {e.name for e in start_events} == {"tool_a", "tool_b"}

        assert len(result_events) == 2
        results = {e.name: e.result for e in result_events}
        assert results["tool_a"] == "result_a"
        assert results["tool_b"] == "result_b"


class TestStreamingGuardrails:
    @pytest.mark.asyncio
    async def test_input_guardrail_blocks(self, mock_async_llm: MockAsyncLLM):
        from naru_agent.guardrails.base import BaseGuardrail, GuardrailResult

        class BlockAll(BaseGuardrail):
            def check_input(self, text):
                return GuardrailResult(passed=False, reason="blocked")

            def check_output(self, text):
                return GuardrailResult(passed=True)

        agent = _make_agent(mock_async_llm, guardrails=[BlockAll()])
        runner = Runner(agent)

        events = await _collect_events(runner, "anything")

        assert len(events) == 1
        assert isinstance(events[0], ErrorEvent)
        assert "blocked" in events[0].error


class TestStreamingMaxIterations:
    @pytest.mark.asyncio
    async def test_max_iterations_yields_error(self, mock_async_llm: MockAsyncLLM):
        def dummy() -> str:
            return "ok"

        tool = FunctionTool(dummy, name="dummy", description="Dummy")

        # Always return tool calls — will hit max_iterations
        args_str = json.dumps({})
        for _ in range(3):
            tc_chunks = [
                StreamChunk(tool_call_deltas=[{"index": 0, "id": f"tc_{_}", "name": "dummy", "arguments": args_str}]),
                StreamChunk(finish_reason="tool_calls"),
            ]
            mock_async_llm.queue_stream_sequence(tc_chunks)

        agent = _make_agent(mock_async_llm, tools=[tool], max_iterations=3)
        runner = Runner(agent)

        events = await _collect_events(runner, "loop")

        error_events = [e for e in events if isinstance(e, ErrorEvent)]
        assert len(error_events) == 1
        assert "Max iterations" in error_events[0].error


# ---------------------------------------------------------------------------
# Edge-case tests
# ---------------------------------------------------------------------------

class TestStreamingMalformedJSON:
    """Fix #4: _finalize_tool_calls logs warning on malformed JSON."""

    @pytest.mark.asyncio
    async def test_malformed_arguments_logged_and_defaults_to_empty(self, caplog):
        accumulated = {
            0: {"id": "tc_1", "name": "my_tool", "arguments": "{invalid json!!!"},
        }
        with caplog.at_level(logging.WARNING, logger="naru_agent.streaming"):
            result = _finalize_tool_calls(accumulated)

        assert len(result) == 1
        assert result[0]["arguments"] == {}
        assert "Failed to parse tool call arguments" in caplog.text
        assert "my_tool" in caplog.text

    @pytest.mark.asyncio
    async def test_empty_arguments_defaults_to_empty_dict(self):
        accumulated = {0: {"id": "tc_1", "name": "my_tool", "arguments": ""}}
        result = _finalize_tool_calls(accumulated)
        assert result[0]["arguments"] == {}


class TestStreamingToolCallAccumulation:
    """Edge cases for _accumulate_tool_call_chunks."""

    def test_delta_without_index_defaults_to_zero(self):
        acc: dict[int, dict] = {}
        _accumulate_tool_call_chunks(acc, [{"id": "tc_1", "name": "foo", "arguments": ""}])
        assert 0 in acc
        assert acc[0]["id"] == "tc_1"

    def test_multiple_name_chunks_concatenate(self):
        """Name split across chunks should concatenate correctly."""
        acc: dict[int, dict] = {}
        _accumulate_tool_call_chunks(acc, [{"index": 0, "id": "tc_1", "name": "get_", "arguments": ""}])
        _accumulate_tool_call_chunks(acc, [{"index": 0, "name": "weather", "arguments": ""}])
        assert acc[0]["name"] == "get_weather"

    def test_id_overwrites_not_concatenates(self):
        """ID should be replaced, not concatenated."""
        acc: dict[int, dict] = {}
        _accumulate_tool_call_chunks(acc, [{"index": 0, "id": "first_id", "name": "t", "arguments": ""}])
        _accumulate_tool_call_chunks(acc, [{"index": 0, "id": "second_id"}])
        assert acc[0]["id"] == "second_id"


class TestStreamingToolError:
    """Tool errors during streaming should be captured, not crash."""

    @pytest.mark.asyncio
    async def test_tool_error_yields_error_in_result(self, mock_async_llm: MockAsyncLLM):
        def exploding_tool() -> str:
            raise RuntimeError("kaboom")

        tool = FunctionTool(exploding_tool, name="boom", description="Explodes")
        mock_async_llm.set_stream_tool_call("boom", {}, final_text="After error")

        agent = _make_agent(mock_async_llm, tools=[tool])
        runner = Runner(agent)

        events = await _collect_events(runner, "do it")

        result_events = [e for e in events if isinstance(e, ToolResultEvent)]
        assert len(result_events) == 1
        assert "Error" in result_events[0].result
        assert "kaboom" in result_events[0].result

    @pytest.mark.asyncio
    async def test_unknown_tool_yields_error_in_result(self, mock_async_llm: MockAsyncLLM):
        """LLM calls a tool that doesn't exist."""
        tc_chunks = [
            StreamChunk(tool_call_deltas=[{"index": 0, "id": "tc_1", "name": "nonexistent", "arguments": ""}]),
            StreamChunk(tool_call_deltas=[{"index": 0, "arguments": "{}"}]),
            StreamChunk(finish_reason="tool_calls"),
        ]
        mock_async_llm.queue_stream_sequence(tc_chunks)
        mock_async_llm.set_stream_text("ok")

        agent = _make_agent(mock_async_llm, tools=[])
        runner = Runner(agent)

        events = await _collect_events(runner, "test")

        result_events = [e for e in events if isinstance(e, ToolResultEvent)]
        assert len(result_events) == 1
        assert "Unknown tool" in result_events[0].result


class TestStreamingGatherException:
    """asyncio.gather with return_exceptions=True should not crash stream."""

    @pytest.mark.asyncio
    async def test_cancelled_tool_does_not_crash_stream(self, mock_async_llm: MockAsyncLLM):
        """If a tool raises CancelledError, stream should still complete."""
        import asyncio

        call_count = 0

        async def flaky_tool() -> str:
            nonlocal call_count
            call_count += 1
            raise asyncio.CancelledError("cancelled")

        tool = FunctionTool(flaky_tool, name="flaky", description="Flaky")

        # Override arun to raise CancelledError directly (bypass the try/except in _execute_tool_async)
        original_execute = Runner._execute_tool_async

        async def patched_execute(self_runner, tc):
            if tc["name"] == "flaky":
                raise asyncio.CancelledError("cancelled")
            return await original_execute(self_runner, tc)

        mock_async_llm.set_stream_tool_call("flaky", {}, final_text="After")
        agent = _make_agent(mock_async_llm, tools=[tool])
        runner = Runner(agent)
        runner._execute_tool_async = patched_execute.__get__(runner, Runner)

        events = await _collect_events(runner, "do it")

        result_events = [e for e in events if isinstance(e, ToolResultEvent)]
        assert len(result_events) == 1
        assert "Error" in result_events[0].result or "Cancel" in result_events[0].result


class TestStreamingEventBusEmission:
    """Fix #5: run_stream() should emit before/after_tool_call events."""

    @pytest.mark.asyncio
    async def test_run_stream_emits_tool_events(self, mock_async_llm: MockAsyncLLM):
        def my_tool() -> str:
            return "result"

        tool = FunctionTool(my_tool, name="my_tool", description="Test")
        mock_async_llm.set_stream_tool_call("my_tool", {}, final_text="Done")

        emitted_events = []
        bus = EventBus()
        bus.on("before_tool_call", lambda data: emitted_events.append(("before", data)))
        bus.on("after_tool_call", lambda data: emitted_events.append(("after", data)))

        agent = _make_agent(mock_async_llm, tools=[tool])
        runner = Runner(agent, event_bus=bus)

        await _collect_events(runner, "test")

        before_events = [e for e in emitted_events if e[0] == "before"]
        after_events = [e for e in emitted_events if e[0] == "after"]

        assert len(before_events) == 1
        assert before_events[0][1]["tool"] == "my_tool"
        assert len(after_events) == 1
        assert after_events[0][1]["tool"] == "my_tool"
        assert after_events[0][1]["result_length"] == len("result")
