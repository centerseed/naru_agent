"""Comprehensive tests for session stores and run_stream + session integration.

Covers:
- InMemorySessionStore CRUD + isolation (deepcopy)
- RedisSessionStore CRUD + TTL edge cases + corrupted data
- run_stream() session load/save on all code paths
- Parameter combinations (session_id/session_store partial/missing)
- Failure modes (store.get/save exceptions)
- Session content format correctness (with and without tool calls)
- Multi-turn accumulation
- Max iterations session save
- Guardrail blocked — no save
"""
from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock

import pytest

from naru_agent.agent import Agent
from naru_agent.runner import Runner
from naru_agent.session.memory_store import InMemorySessionStore
from naru_agent.session.redis_store import RedisSessionStore
from naru_agent.streaming import (
    DoneEvent,
    ErrorEvent,
    StreamChunk,
    TextDeltaEvent,
    ToolCallStartEvent,
    ToolResultEvent,
)
from naru_agent.tools.base import FunctionTool

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


# ===========================================================================
# 1. InMemorySessionStore — unit tests
# ===========================================================================

class TestInMemorySessionStoreCRUD:
    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self):
        store = InMemorySessionStore()
        assert await store.get("nope") is None

    @pytest.mark.asyncio
    async def test_save_and_get(self):
        store = InMemorySessionStore()
        history = [{"role": "user", "content": "hello"}]
        await store.save("s1", history)

        result = await store.get("s1")
        assert result == history
        assert result is not history

    @pytest.mark.asyncio
    async def test_delete(self):
        store = InMemorySessionStore()
        await store.save("s1", [{"role": "user", "content": "hi"}])
        await store.delete("s1")
        assert await store.get("s1") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_no_error(self):
        store = InMemorySessionStore()
        await store.delete("nope")  # Should not raise

    @pytest.mark.asyncio
    async def test_overwrite_existing_session(self):
        store = InMemorySessionStore()
        await store.save("s1", [{"role": "user", "content": "v1"}])
        await store.save("s1", [{"role": "user", "content": "v2"}])
        result = await store.get("s1")
        assert result == [{"role": "user", "content": "v2"}]

    @pytest.mark.asyncio
    async def test_multiple_sessions_isolated(self):
        store = InMemorySessionStore()
        await store.save("s1", [{"role": "user", "content": "a"}])
        await store.save("s2", [{"role": "user", "content": "b"}])
        assert (await store.get("s1"))[0]["content"] == "a"
        assert (await store.get("s2"))[0]["content"] == "b"

    @pytest.mark.asyncio
    async def test_save_empty_list(self):
        store = InMemorySessionStore()
        await store.save("s1", [])
        result = await store.get("s1")
        assert result == []
        assert result is not None  # Empty list is NOT None


class TestInMemorySessionStoreLazyLock:
    """Lock is created lazily inside the event loop, not at __init__ time."""

    def test_init_does_not_create_lock(self):
        """InMemorySessionStore() should not create asyncio.Lock at init time."""
        store = InMemorySessionStore()
        assert store._lock is None

    @pytest.mark.asyncio
    async def test_lock_created_on_first_use(self):
        store = InMemorySessionStore()
        assert store._lock is None
        await store.save("s1", [{"role": "user", "content": "hi"}])
        assert store._lock is not None

    @pytest.mark.asyncio
    async def test_same_lock_reused(self):
        store = InMemorySessionStore()
        await store.save("s1", [])
        lock1 = store._lock
        await store.get("s1")
        lock2 = store._lock
        assert lock1 is lock2


class TestInMemorySessionStoreIsolation:
    """Deepcopy ensures mutation safety."""

    @pytest.mark.asyncio
    async def test_mutation_after_get_does_not_affect_store(self):
        store = InMemorySessionStore()
        await store.save("s1", [{"role": "user", "content": "hello"}])

        retrieved = await store.get("s1")
        retrieved[0]["content"] = "MUTATED"
        retrieved.append({"role": "assistant", "content": "extra"})

        stored = await store.get("s1")
        assert stored == [{"role": "user", "content": "hello"}]
        assert len(stored) == 1

    @pytest.mark.asyncio
    async def test_mutation_after_save_does_not_affect_store(self):
        store = InMemorySessionStore()
        history = [{"role": "user", "content": "hello"}]
        await store.save("s1", history)

        history[0]["content"] = "MUTATED"

        stored = await store.get("s1")
        assert stored[0]["content"] == "hello"

    @pytest.mark.asyncio
    async def test_nested_dict_mutation_safe(self):
        """Even nested structures should be isolated."""
        store = InMemorySessionStore()
        history = [{"role": "assistant", "content": "text", "metadata": {"key": "original"}}]
        await store.save("s1", history)

        retrieved = await store.get("s1")
        retrieved[0]["metadata"]["key"] = "MUTATED"

        stored = await store.get("s1")
        assert stored[0]["metadata"]["key"] == "original"


# ===========================================================================
# 2. RedisSessionStore — unit tests
# ===========================================================================

class TestRedisSessionStoreCRUD:
    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing(self):
        client = AsyncMock()
        client.get = AsyncMock(return_value=None)
        store = RedisSessionStore(client)

        result = await store.get("nope")
        assert result is None
        client.get.assert_called_once_with("naru:session:nope")

    @pytest.mark.asyncio
    async def test_save_and_get_roundtrip(self):
        storage = {}

        async def mock_set(key, value):
            storage[key] = value

        async def mock_get(key):
            return storage.get(key)

        client = AsyncMock()
        client.set = AsyncMock(side_effect=mock_set)
        client.get = AsyncMock(side_effect=mock_get)

        store = RedisSessionStore(client)
        history = [{"role": "user", "content": "hi"}]

        await store.save("s1", history)
        result = await store.get("s1")
        assert result == history

    @pytest.mark.asyncio
    async def test_save_with_ttl_uses_setex(self):
        client = AsyncMock()
        client.setex = AsyncMock()

        store = RedisSessionStore(client, ttl=3600)
        await store.save("s1", [{"role": "user", "content": "hi"}])

        client.setex.assert_called_once()
        args = client.setex.call_args
        assert args[0][0] == "naru:session:s1"
        assert args[0][1] == 3600

    @pytest.mark.asyncio
    async def test_delete(self):
        client = AsyncMock()
        client.delete = AsyncMock()

        store = RedisSessionStore(client)
        await store.delete("s1")
        client.delete.assert_called_once_with("naru:session:s1")

    @pytest.mark.asyncio
    async def test_custom_prefix(self):
        client = AsyncMock()
        client.get = AsyncMock(return_value=None)

        store = RedisSessionStore(client, prefix="myapp:")
        await store.get("s1")
        client.get.assert_called_once_with("myapp:s1")


class TestRedisSessionStoreTTLEdgeCases:
    @pytest.mark.asyncio
    async def test_ttl_zero_uses_setex(self):
        """ttl=0 is valid (immediate expiry) and should use setex, not set."""
        client = AsyncMock()
        client.setex = AsyncMock()

        store = RedisSessionStore(client, ttl=0)
        await store.save("s1", [{"role": "user", "content": "hi"}])

        client.setex.assert_called_once()
        assert client.setex.call_args[0][1] == 0

    @pytest.mark.asyncio
    async def test_ttl_none_uses_set(self):
        """ttl=None (default) should use set, not setex."""
        client = AsyncMock()
        client.set = AsyncMock()

        store = RedisSessionStore(client, ttl=None)
        await store.save("s1", [{"role": "user", "content": "hi"}])

        client.set.assert_called_once()


class TestRedisSessionStoreCorruptedData:
    @pytest.mark.asyncio
    async def test_corrupted_json_returns_none(self):
        """Corrupted data in Redis should return None, not crash."""
        client = AsyncMock()
        client.get = AsyncMock(return_value=b"not valid json {{{")

        store = RedisSessionStore(client)
        result = await store.get("s1")
        assert result is None

    @pytest.mark.asyncio
    async def test_corrupted_json_logs_error(self, caplog):
        client = AsyncMock()
        client.get = AsyncMock(return_value=b"broken")

        store = RedisSessionStore(client)
        with caplog.at_level(logging.ERROR, logger="naru_agent.session.redis_store"):
            await store.get("s1")

        assert "Corrupted session data" in caplog.text
        assert "s1" in caplog.text

    @pytest.mark.asyncio
    async def test_non_string_data_returns_none(self):
        """Non-bytes/non-string from Redis should not crash."""
        client = AsyncMock()
        client.get = AsyncMock(return_value=12345)  # unexpected type

        store = RedisSessionStore(client)
        result = await store.get("s1")
        # json.loads(12345) raises TypeError → caught → returns None
        assert result is None

    @pytest.mark.asyncio
    async def test_unicode_content_preserved(self):
        """Non-ASCII characters should survive roundtrip."""
        storage = {}

        async def mock_set(key, value):
            storage[key] = value

        async def mock_get(key):
            return storage.get(key)

        client = AsyncMock()
        client.set = AsyncMock(side_effect=mock_set)
        client.get = AsyncMock(side_effect=mock_get)

        store = RedisSessionStore(client)
        history = [{"role": "user", "content": "你好世界 🌍"}]
        await store.save("s1", history)
        result = await store.get("s1")
        assert result[0]["content"] == "你好世界 🌍"


# ===========================================================================
# 3. run_stream + session — parameter combinations
# ===========================================================================

class TestSessionParameterCombinations:
    """Ensure all combinations of session_id / session_store are handled."""

    @pytest.mark.asyncio
    async def test_no_session_params(self, mock_async_llm: MockAsyncLLM):
        """No session_id, no session_store → normal operation."""
        mock_async_llm.set_stream_text("Hello")
        agent = _make_agent(mock_async_llm)
        runner = Runner(agent)

        events = await _collect_events(runner, "hi")
        done = [e for e in events if isinstance(e, DoneEvent)]
        assert len(done) == 1
        assert done[0].content == "Hello"

    @pytest.mark.asyncio
    async def test_session_id_without_store(self, mock_async_llm: MockAsyncLLM):
        """session_id provided but no store → should work normally, no save."""
        mock_async_llm.set_stream_text("Hello")
        agent = _make_agent(mock_async_llm)
        runner = Runner(agent)

        events = await _collect_events(runner, "hi", session_id="sess_1")
        done = [e for e in events if isinstance(e, DoneEvent)]
        assert len(done) == 1

    @pytest.mark.asyncio
    async def test_session_store_without_id(self, mock_async_llm: MockAsyncLLM):
        """session_store provided but no session_id → should work normally, no save."""
        mock_async_llm.set_stream_text("Hello")
        store = InMemorySessionStore()
        agent = _make_agent(mock_async_llm)
        runner = Runner(agent)

        events = await _collect_events(runner, "hi", session_store=store)
        done = [e for e in events if isinstance(e, DoneEvent)]
        assert len(done) == 1
        # Nothing saved
        assert await store.get("anything") is None

    @pytest.mark.asyncio
    async def test_conversation_history_used_without_session(self, mock_async_llm: MockAsyncLLM):
        """conversation_history should be used when no session is configured."""
        mock_async_llm.set_stream_text("Response")
        agent = _make_agent(mock_async_llm)
        runner = Runner(agent)

        history = [
            {"role": "user", "content": "prev_msg"},
            {"role": "assistant", "content": "prev_reply"},
        ]
        await _collect_events(runner, "new_msg", conversation_history=history)

        msgs = mock_async_llm.chat_calls[0]["messages"]
        contents = [m.get("content", "") for m in msgs]
        assert "prev_msg" in " ".join(str(c) for c in contents)

    @pytest.mark.asyncio
    async def test_session_takes_priority_over_conversation_history(self, mock_async_llm: MockAsyncLLM):
        """When both session and conversation_history exist, session wins."""
        store = InMemorySessionStore()
        await store.save("sess_1", [
            {"role": "user", "content": "session_msg"},
            {"role": "assistant", "content": "session_reply"},
        ])

        mock_async_llm.set_stream_text("Response")
        agent = _make_agent(mock_async_llm)
        runner = Runner(agent)

        conversation_history = [
            {"role": "user", "content": "conv_msg"},
            {"role": "assistant", "content": "conv_reply"},
        ]
        await _collect_events(
            runner, "new",
            session_id="sess_1",
            session_store=store,
            conversation_history=conversation_history,
        )

        msgs = mock_async_llm.chat_calls[0]["messages"]
        all_content = " ".join(str(m.get("content", "")) for m in msgs)
        assert "session_msg" in all_content
        assert "conv_msg" not in all_content


# ===========================================================================
# 4. run_stream + session — load/save correctness
# ===========================================================================

class TestSessionLoadSave:
    @pytest.mark.asyncio
    async def test_basic_save(self, mock_async_llm: MockAsyncLLM):
        """Simple text response → session saved with user + assistant messages."""
        mock_async_llm.set_stream_text("Hi there!")
        store = InMemorySessionStore()
        agent = _make_agent(mock_async_llm)
        runner = Runner(agent)

        await _collect_events(
            runner, "hello",
            session_id="sess_1",
            session_store=store,
        )

        history = await store.get("sess_1")
        assert history is not None
        assert any(m["role"] == "user" and m["content"] == "hello" for m in history)
        assert any(m["role"] == "assistant" and m["content"] == "Hi there!" for m in history)

    @pytest.mark.asyncio
    async def test_session_excludes_system_message(self, mock_async_llm: MockAsyncLLM):
        """Saved session should NOT include the system message."""
        mock_async_llm.set_stream_text("Response")
        store = InMemorySessionStore()
        agent = _make_agent(mock_async_llm)
        runner = Runner(agent)

        await _collect_events(runner, "hi", session_id="sess_1", session_store=store)

        history = await store.get("sess_1")
        assert all(m["role"] != "system" for m in history)

    @pytest.mark.asyncio
    async def test_session_with_tool_calls_saved_correctly(self, mock_async_llm: MockAsyncLLM):
        """Session should include: user, assistant(tool_calls), tool(result), assistant(final)."""
        def greet(name: str) -> str:
            return f"Hi {name}!"

        tool = FunctionTool(greet, name="greet", description="Greet")
        mock_async_llm.set_stream_tool_call("greet", {"name": "World"}, final_text="Done greeting")

        store = InMemorySessionStore()
        agent = _make_agent(mock_async_llm, tools=[tool])
        runner = Runner(agent)

        await _collect_events(runner, "say hi", session_id="sess_1", session_store=store)

        history = await store.get("sess_1")
        assert history is not None

        roles = [m["role"] for m in history]
        # user → assistant(with tool_calls) → tool → assistant(final text)
        assert roles[0] == "user"
        assert roles[1] == "assistant"
        assert "tool_calls" in history[1]  # assistant message contains tool_calls
        assert roles[2] == "tool"
        assert history[2]["content"] == "Hi World!"
        assert roles[3] == "assistant"
        assert history[3]["content"] == "Done greeting"

    @pytest.mark.asyncio
    async def test_second_call_loads_history(self, mock_async_llm: MockAsyncLLM):
        """Second call with same session_id should include first conversation."""
        store = InMemorySessionStore()
        agent = _make_agent(mock_async_llm)
        runner = Runner(agent)

        mock_async_llm.set_stream_text("Response 1")
        await _collect_events(runner, "msg1", session_id="sess_1", session_store=store)

        mock_async_llm.set_stream_text("Response 2")
        await _collect_events(runner, "msg2", session_id="sess_1", session_store=store)

        # The second LLM call should have full history
        second_call_msgs = mock_async_llm.chat_calls[1]["messages"]
        all_content = " ".join(str(m.get("content", "")) for m in second_call_msgs)
        assert "msg1" in all_content
        assert "Response 1" in all_content
        assert "msg2" in all_content

    @pytest.mark.asyncio
    async def test_three_turn_accumulation(self, mock_async_llm: MockAsyncLLM):
        """Three turns should accumulate correctly."""
        store = InMemorySessionStore()
        agent = _make_agent(mock_async_llm)
        runner = Runner(agent)

        for i in range(3):
            mock_async_llm.set_stream_text(f"reply_{i}")
            await _collect_events(runner, f"msg_{i}", session_id="sess_1", session_store=store)

        history = await store.get("sess_1")
        # 3 turns × (user + assistant) = 6 messages
        assert len(history) == 6
        assert history[0] == {"role": "user", "content": "msg_0"}
        assert history[1] == {"role": "assistant", "content": "reply_0"}
        assert history[4] == {"role": "user", "content": "msg_2"}
        assert history[5] == {"role": "assistant", "content": "reply_2"}

    @pytest.mark.asyncio
    async def test_empty_session_does_not_use_conversation_history(self, mock_async_llm: MockAsyncLLM):
        """Empty session [] should NOT fall back to conversation_history.

        This tests the fix for the `if session_history:` falsy bug.
        An existing session that happens to be empty means the user started fresh.
        """
        store = InMemorySessionStore()
        await store.save("sess_1", [])  # Explicitly empty session

        mock_async_llm.set_stream_text("Response")
        agent = _make_agent(mock_async_llm)
        runner = Runner(agent)

        conversation_history = [
            {"role": "user", "content": "should_not_appear"},
        ]
        await _collect_events(
            runner, "hi",
            session_id="sess_1",
            session_store=store,
            conversation_history=conversation_history,
        )

        msgs = mock_async_llm.chat_calls[0]["messages"]
        all_content = " ".join(str(m.get("content", "")) for m in msgs)
        # conversation_history should NOT have been used
        assert "should_not_appear" not in all_content


# ===========================================================================
# 5. run_stream + session — failure modes
# ===========================================================================

class TestSessionFailureModes:
    @pytest.mark.asyncio
    async def test_store_get_exception_degrades_gracefully(self, mock_async_llm: MockAsyncLLM):
        """If session_store.get() raises, stream should continue without history."""
        mock_async_llm.set_stream_text("Response")

        store = AsyncMock()
        store.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        store.save = AsyncMock()

        agent = _make_agent(mock_async_llm)
        runner = Runner(agent)

        events = await _collect_events(
            runner, "hi",
            session_id="sess_1",
            session_store=store,
        )

        done = [e for e in events if isinstance(e, DoneEvent)]
        assert len(done) == 1
        assert done[0].content == "Response"
        # save should still have been attempted
        store.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_get_exception_logged(self, mock_async_llm: MockAsyncLLM, caplog):
        mock_async_llm.set_stream_text("Response")

        store = AsyncMock()
        store.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        store.save = AsyncMock()

        agent = _make_agent(mock_async_llm)
        runner = Runner(agent)

        with caplog.at_level(logging.ERROR, logger="naru_agent.runner"):
            await _collect_events(runner, "hi", session_id="s1", session_store=store)

        assert "Failed to load session" in caplog.text

    @pytest.mark.asyncio
    async def test_store_save_exception_still_yields_done(self, mock_async_llm: MockAsyncLLM):
        """If session_store.save() raises, DoneEvent should STILL be yielded."""
        mock_async_llm.set_stream_text("Important response")

        store = InMemorySessionStore()
        # Monkey-patch save to fail
        original_save = store.save

        async def failing_save(session_id, history):
            raise ConnectionError("Redis write failed")

        store.save = failing_save

        agent = _make_agent(mock_async_llm)
        runner = Runner(agent)

        events = await _collect_events(
            runner, "hi",
            session_id="sess_1",
            session_store=store,
        )

        done = [e for e in events if isinstance(e, DoneEvent)]
        assert len(done) == 1
        assert done[0].content == "Important response"

    @pytest.mark.asyncio
    async def test_store_save_exception_logged(self, mock_async_llm: MockAsyncLLM, caplog):
        mock_async_llm.set_stream_text("Response")

        store = AsyncMock()
        store.get = AsyncMock(return_value=None)
        store.save = AsyncMock(side_effect=ConnectionError("write failed"))

        agent = _make_agent(mock_async_llm)
        runner = Runner(agent)

        with caplog.at_level(logging.ERROR, logger="naru_agent.runner"):
            await _collect_events(runner, "hi", session_id="s1", session_store=store)

        assert "Failed to save session" in caplog.text


# ===========================================================================
# 6. run_stream + session — max iterations
# ===========================================================================

class TestSessionMaxIterations:
    @pytest.mark.asyncio
    async def test_max_iterations_saves_session(self, mock_async_llm: MockAsyncLLM):
        """Even when hitting max iterations, partial session should be saved."""
        def dummy() -> str:
            return "ok"

        tool = FunctionTool(dummy, name="dummy", description="Dummy")
        store = InMemorySessionStore()

        args_str = json.dumps({})
        for i in range(2):
            tc_chunks = [
                StreamChunk(tool_call_deltas=[
                    {"index": 0, "id": f"tc_{i}", "name": "dummy", "arguments": args_str},
                ]),
                StreamChunk(finish_reason="tool_calls"),
            ]
            mock_async_llm.queue_stream_sequence(tc_chunks)

        agent = _make_agent(mock_async_llm, tools=[tool], max_iterations=2)
        runner = Runner(agent)

        events = await _collect_events(
            runner, "loop",
            session_id="sess_1",
            session_store=store,
        )

        error_events = [e for e in events if isinstance(e, ErrorEvent)]
        assert len(error_events) == 1

        # Session was saved with partial conversation
        history = await store.get("sess_1")
        assert history is not None
        assert len(history) > 0
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "loop"

    @pytest.mark.asyncio
    async def test_max_iterations_save_failure_still_yields_error(self, mock_async_llm: MockAsyncLLM):
        """Save failure on max iterations should not swallow the ErrorEvent."""
        def dummy() -> str:
            return "ok"

        tool = FunctionTool(dummy, name="dummy", description="Dummy")

        args_str = json.dumps({})
        tc_chunks = [
            StreamChunk(tool_call_deltas=[
                {"index": 0, "id": "tc_0", "name": "dummy", "arguments": args_str},
            ]),
            StreamChunk(finish_reason="tool_calls"),
        ]
        mock_async_llm.queue_stream_sequence(tc_chunks)

        store = AsyncMock()
        store.get = AsyncMock(return_value=None)
        store.save = AsyncMock(side_effect=ConnectionError("save failed"))

        agent = _make_agent(mock_async_llm, tools=[tool], max_iterations=1)
        runner = Runner(agent)

        events = await _collect_events(
            runner, "loop",
            session_id="sess_1",
            session_store=store,
        )

        error_events = [e for e in events if isinstance(e, ErrorEvent)]
        assert len(error_events) == 1
        assert "Max iterations" in error_events[0].error


# ===========================================================================
# 7. run_stream + session — guardrail interaction
# ===========================================================================

class TestSessionGuardrailInteraction:
    @pytest.mark.asyncio
    async def test_input_guardrail_block_does_not_save_session(self, mock_async_llm: MockAsyncLLM):
        """If input guardrail blocks, session should NOT be saved."""
        from naru_agent.guardrails.base import BaseGuardrail, GuardrailResult

        class BlockAll(BaseGuardrail):
            def check_input(self, text):
                return GuardrailResult(passed=False, reason="blocked")

            def check_output(self, text):
                return GuardrailResult(passed=True)

        store = InMemorySessionStore()
        agent = _make_agent(mock_async_llm, guardrails=[BlockAll()])
        runner = Runner(agent)

        events = await _collect_events(
            runner, "anything",
            session_id="sess_1",
            session_store=store,
        )

        assert isinstance(events[0], ErrorEvent)
        # Session should NOT have been saved
        assert await store.get("sess_1") is None

    @pytest.mark.asyncio
    async def test_output_guardrail_saves_modified_content(self, mock_async_llm: MockAsyncLLM):
        """Output guardrail modifies text → saved session should have modified text."""
        from naru_agent.guardrails.base import BaseGuardrail, GuardrailResult

        class RedactSSN(BaseGuardrail):
            def check_input(self, text):
                return GuardrailResult(passed=True)

            def check_output(self, text):
                if "secret" in text:
                    return GuardrailResult(
                        passed=False,
                        modified_text=text.replace("secret", "[REDACTED]"),
                    )
                return GuardrailResult(passed=True)

        mock_async_llm.set_stream_text("The secret code")
        store = InMemorySessionStore()
        agent = _make_agent(mock_async_llm, guardrails=[RedactSSN()])
        runner = Runner(agent)

        events = await _collect_events(
            runner, "tell me",
            session_id="sess_1",
            session_store=store,
        )

        done = [e for e in events if isinstance(e, DoneEvent)]
        assert "[REDACTED]" in done[0].content

        # Session should have the REDACTED version
        history = await store.get("sess_1")
        assistant_msg = next(m for m in history if m["role"] == "assistant")
        assert "[REDACTED]" in assistant_msg["content"]
        assert "secret" not in assistant_msg["content"]


# ===========================================================================
# 8. Session history format — LLM compatibility
# ===========================================================================

class TestSessionHistoryFormat:
    @pytest.mark.asyncio
    async def test_loaded_history_produces_valid_llm_messages(self, mock_async_llm: MockAsyncLLM):
        """History loaded from session should be valid for LLM consumption.

        Specifically: messages[1:] loaded from session must be compatible with
        being sent directly to the LLM alongside the system message.
        """
        store = InMemorySessionStore()
        agent = _make_agent(mock_async_llm)
        runner = Runner(agent)

        # Turn 1
        mock_async_llm.set_stream_text("I can help!")
        await _collect_events(runner, "Help me", session_id="sess_1", session_store=store)

        # Turn 2 — verify messages sent to LLM
        mock_async_llm.set_stream_text("Sure thing")
        await _collect_events(runner, "Thanks", session_id="sess_1", session_store=store)

        second_call_msgs = mock_async_llm.chat_calls[1]["messages"]

        # Structure should be: system, user("Help me"), assistant("I can help!"), user("Thanks")
        assert second_call_msgs[0]["role"] == "system"
        assert second_call_msgs[1]["role"] == "user"
        assert second_call_msgs[1]["content"] == "Help me"
        assert second_call_msgs[2]["role"] == "assistant"
        assert second_call_msgs[2]["content"] == "I can help!"
        assert second_call_msgs[3]["role"] == "user"
        assert second_call_msgs[3]["content"] == "Thanks"

    @pytest.mark.asyncio
    async def test_tool_call_history_format_valid_for_llm(self, mock_async_llm: MockAsyncLLM):
        """After tool calls, the loaded session should produce valid LLM API messages.

        LLM APIs require assistant messages with tool_calls to be followed by
        matching tool result messages with the correct tool_call_id.
        """
        def calc(x: int) -> str:
            return str(x * 2)

        tool = FunctionTool(calc, name="calc", description="Calculate")
        store = InMemorySessionStore()

        # Turn 1: tool call → result → final text
        mock_async_llm.set_stream_tool_call("calc", {"x": 5}, final_text="Result is 10")

        agent = _make_agent(mock_async_llm, tools=[tool])
        runner = Runner(agent)

        await _collect_events(runner, "calc 5", session_id="sess_1", session_store=store)

        # Turn 2: verify history structure
        mock_async_llm.set_stream_text("Anything else?")
        await _collect_events(runner, "thanks", session_id="sess_1", session_store=store)

        second_call_msgs = mock_async_llm.chat_calls[2]["messages"]  # index 2 because turn 1 had 2 LLM calls

        # Find the assistant message with tool_calls
        assistant_tc = next(
            (m for m in second_call_msgs if m.get("role") == "assistant" and "tool_calls" in m),
            None,
        )
        assert assistant_tc is not None

        # Find the tool result message
        tool_msg = next(
            (m for m in second_call_msgs if m.get("role") == "tool"),
            None,
        )
        assert tool_msg is not None

        # tool_call_id should match
        tc_id = assistant_tc["tool_calls"][0]["id"]
        assert tool_msg["tool_call_id"] == tc_id
        assert tool_msg["content"] == "10"


# ===========================================================================
# 9. Concurrent session safety (InMemorySessionStore)
# ===========================================================================

class TestSessionConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_different_sessions(self, mock_async_llm: MockAsyncLLM):
        """Two concurrent streams with different session_ids should be isolated."""
        import asyncio

        store = InMemorySessionStore()
        agent = _make_agent(mock_async_llm)
        runner = Runner(agent)

        mock_async_llm.set_stream_text("Reply A")
        mock_async_llm.set_stream_text("Reply B")

        async def run_session(msg, sid):
            return await _collect_events(runner, msg, session_id=sid, session_store=store)

        events_a, events_b = await asyncio.gather(
            run_session("msg_a", "sess_a"),
            run_session("msg_b", "sess_b"),
        )

        # Both should complete
        assert any(isinstance(e, DoneEvent) for e in events_a)
        assert any(isinstance(e, DoneEvent) for e in events_b)

        # Sessions should be isolated
        hist_a = await store.get("sess_a")
        hist_b = await store.get("sess_b")
        assert hist_a is not None
        assert hist_b is not None

        a_contents = [m.get("content") for m in hist_a]
        b_contents = [m.get("content") for m in hist_b]
        assert "msg_a" in a_contents
        assert "msg_b" in b_contents
        assert "msg_b" not in a_contents
        assert "msg_a" not in b_contents
