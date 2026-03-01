"""Tests for NaruAgent orchestration."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from naru_agent.agent import NaruAgent, NaruResult
from naru_agent.guardrails.base import BaseGuardrail, GuardrailResult
from naru_agent.intent.base import BaseIntentClassifier, IntentResult
from naru_agent.knowledge.base import BaseKnowledgeStore, KnowledgeResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class BlockGuardrail(BaseGuardrail):
    def check_input(self, message):
        if "block" in message:
            return GuardrailResult(passed=False, modified_text="Blocked!", reason="keyword")
        return GuardrailResult(passed=True)

    def check_output(self, response):
        if "secret" in response:
            return GuardrailResult(passed=False, modified_text="[REDACTED]")
        return GuardrailResult(passed=True)


class FixedIntentClassifier(BaseIntentClassifier):
    def __init__(self, result: IntentResult):
        self._result = result

    def classify(self, message):
        return self._result


class DummyKnowledgeStore(BaseKnowledgeStore):
    def __init__(self, results=None):
        self._results = results or []
        self.search_called = False

    def search(self, query, top_k=3):
        self.search_called = True
        return self._results


def _make_agno_result(content="Hello!", tool_calls_msgs=None):
    """Create a mock Agno RunResponse."""
    mock_result = MagicMock()
    mock_result.content = content
    mock_result.messages = tool_calls_msgs or []

    mock_metrics = MagicMock()
    mock_metrics.input_tokens = 100
    mock_metrics.output_tokens = 50
    mock_result.metrics = mock_metrics

    return mock_result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNaruResult:
    def test_defaults(self):
        r = NaruResult()
        assert r.content == ""
        assert r.blocked is False
        assert r.usage == {}
        assert r.intent is None
        assert r.tool_calls == []

    def test_custom(self):
        r = NaruResult(content="hi", blocked=True, usage={"total": 5})
        assert r.content == "hi"
        assert r.blocked is True
        assert r.usage["total"] == 5


class TestInputGuardrails:
    def test_blocks_message(self):
        agent = NaruAgent(
            model="test-model",
            guardrails=[BlockGuardrail()],
        )
        with patch.object(agent, "_get_agno_model"):
            result = agent.chat("please block this")
        assert result.blocked is True
        assert result.content == "Blocked!"


class TestOutputGuardrails:
    def test_modifies_output(self):
        agent = NaruAgent(
            model="test-model",
            guardrails=[BlockGuardrail()],
        )
        mock_result = _make_agno_result(content="This is a secret message")

        with patch("naru_agent.agent.AgnoAgent") as MockAgnoAgent:
            mock_agno = MagicMock()
            mock_agno.run.return_value = mock_result
            MockAgnoAgent.return_value = mock_agno

            with patch.object(agent, "_get_agno_model", return_value=MagicMock()):
                result = agent.chat("tell me something")
        assert result.content == "[REDACTED]"


class TestIntentClassification:
    def test_no_classifier_defaults_to_all_true(self):
        agent = NaruAgent(model="test-model")
        mock_result = _make_agno_result()

        with patch("naru_agent.agent.AgnoAgent") as MockAgnoAgent:
            mock_agno = MagicMock()
            mock_agno.run.return_value = mock_result
            MockAgnoAgent.return_value = mock_agno

            with patch.object(agent, "_get_agno_model", return_value=MagicMock()):
                result = agent.chat("hello")
        assert result.intent.needs_knowledge is True
        assert result.intent.needs_tools is True

    def test_nn_intent_skips_knowledge_and_tools(self):
        store = DummyKnowledgeStore(
            results=[KnowledgeResult(text="data", score=0.9)]
        )
        classifier = FixedIntentClassifier(
            IntentResult(needs_knowledge=False, needs_tools=False, raw="NN")
        )
        agent = NaruAgent(
            model="test-model",
            knowledge_store=store,
            intent_classifier=classifier,
            tools=[MagicMock()],
        )

        mock_result = _make_agno_result()
        with patch("naru_agent.agent.AgnoAgent") as MockAgnoAgent:
            mock_agno = MagicMock()
            mock_agno.run.return_value = mock_result
            MockAgnoAgent.return_value = mock_agno

            with patch.object(agent, "_get_agno_model", return_value=MagicMock()):
                result = agent.chat("你好")

        # Knowledge should NOT be searched when intent says NN
        assert not store.search_called
        # Agent should be called without tools
        call_kwargs = MockAgnoAgent.call_args[1]
        assert call_kwargs["tools"] is None
        assert result.intent.raw == "NN"

    def test_yy_intent_fetches_knowledge_and_tools(self):
        store = DummyKnowledgeStore(
            results=[KnowledgeResult(text="knowledge data", score=0.9)]
        )
        classifier = FixedIntentClassifier(
            IntentResult(needs_knowledge=True, needs_tools=True, raw="YY")
        )

        from naru_agent.tools.base import tool as tool_decorator

        @tool_decorator(description="test tool")
        def dummy_tool(x: str) -> str:
            return x

        agent = NaruAgent(
            model="test-model",
            knowledge_store=store,
            intent_classifier=classifier,
            tools=[dummy_tool],
        )

        mock_result = _make_agno_result()
        with patch("naru_agent.agent.AgnoAgent") as MockAgnoAgent:
            mock_agno = MagicMock()
            mock_agno.run.return_value = mock_result
            MockAgnoAgent.return_value = mock_agno

            with patch.object(agent, "_get_agno_model", return_value=MagicMock()):
                with patch("naru_agent.tools.agno_adapter.NaruToolkit") as MockToolkit:
                    mock_tk = MagicMock()
                    mock_tk.toolkit = MagicMock()
                    MockToolkit.return_value = mock_tk
                    result = agent.chat("全馬跑爆了怎麼辦")

        assert store.search_called
        call_kwargs = MockAgnoAgent.call_args[1]
        assert call_kwargs["tools"] is not None
        # Instructions should contain knowledge
        instructions = call_kwargs["instructions"]
        assert any("Knowledge" in i for i in instructions)


class TestMemory:
    def test_memory_fetched_in_prefetch(self):
        mock_memory = MagicMock()
        mock_memory.get_context_string.return_value = "User prefers morning runs"

        agent = NaruAgent(
            model="test-model",
            memory=mock_memory,
        )

        mock_result = _make_agno_result()
        with patch("naru_agent.agent.AgnoAgent") as MockAgnoAgent:
            mock_agno = MagicMock()
            mock_agno.run.return_value = mock_result
            MockAgnoAgent.return_value = mock_agno

            with patch.object(agent, "_get_agno_model", return_value=MagicMock()):
                result = agent.chat("hi", user_id="user_1")

        mock_memory.get_context_string.assert_called_once()
        instructions = MockAgnoAgent.call_args[1]["instructions"]
        assert any("Memory" in i for i in instructions)

    def test_memory_save_in_background(self):
        mock_memory = MagicMock()
        mock_memory.get_context_string.return_value = ""

        # Make content long enough to trigger save
        long_content = "A" * 200
        agent = NaruAgent(
            model="test-model",
            memory=mock_memory,
        )

        mock_result = _make_agno_result(content=long_content)
        with patch("naru_agent.agent.AgnoAgent") as MockAgnoAgent:
            mock_agno = MagicMock()
            mock_agno.run.return_value = mock_result
            MockAgnoAgent.return_value = mock_agno

            with patch.object(agent, "_get_agno_model", return_value=MagicMock()):
                result = agent.chat("tell me a story", user_id="user_1")

        # Wait for background thread
        time.sleep(0.2)
        mock_memory.add.assert_called_once()


class TestToolCallsExtraction:
    def test_extracts_tool_names(self):
        # Create mock messages with tool calls
        mock_msg = MagicMock()
        mock_msg.tool_calls = [
            {"function": {"name": "search"}, "id": "1"},
            {"function": {"name": "calculate"}, "id": "2"},
        ]
        mock_msg.role = "assistant"

        agent = NaruAgent(model="test-model")
        mock_result = _make_agno_result(
            content="Result",
            tool_calls_msgs=[mock_msg],
        )

        with patch("naru_agent.agent.AgnoAgent") as MockAgnoAgent:
            mock_agno = MagicMock()
            mock_agno.run.return_value = mock_result
            MockAgnoAgent.return_value = mock_agno

            with patch.object(agent, "_get_agno_model", return_value=MagicMock()):
                result = agent.chat("test")

        assert "search" in result.tool_calls
        assert "calculate" in result.tool_calls


class TestTimings:
    def test_timings_recorded(self):
        agent = NaruAgent(model="test-model")
        mock_result = _make_agno_result()

        with patch("naru_agent.agent.AgnoAgent") as MockAgnoAgent:
            mock_agno = MagicMock()
            mock_agno.run.return_value = mock_result
            MockAgnoAgent.return_value = mock_agno

            with patch.object(agent, "_get_agno_model", return_value=MagicMock()):
                result = agent.chat("hello")

        assert "prefetch" in result.timings
        assert "agent_run" in result.timings
        assert "total" in result.timings


class TestUsageExtraction:
    def test_usage_from_metrics(self):
        agent = NaruAgent(model="test-model")
        mock_result = _make_agno_result()

        with patch("naru_agent.agent.AgnoAgent") as MockAgnoAgent:
            mock_agno = MagicMock()
            mock_agno.run.return_value = mock_result
            MockAgnoAgent.return_value = mock_agno

            with patch.object(agent, "_get_agno_model", return_value=MagicMock()):
                result = agent.chat("test")

        assert result.usage["input"] == 100
        assert result.usage["output"] == 50
        assert result.usage["total"] == 150


class TestPrefetchHooks:
    def test_custom_hooks_executed(self):
        hook_called = []

        def my_hook(message, user_id):
            hook_called.append(True)
            return "hook_data"

        agent = NaruAgent(
            model="test-model",
            prefetch_hooks=[my_hook],
        )

        mock_result = _make_agno_result()
        with patch("naru_agent.agent.AgnoAgent") as MockAgnoAgent:
            mock_agno = MagicMock()
            mock_agno.run.return_value = mock_result
            MockAgnoAgent.return_value = mock_agno

            with patch.object(agent, "_get_agno_model", return_value=MagicMock()):
                result = agent.chat("hi")

        assert len(hook_called) == 1
        instructions = MockAgnoAgent.call_args[1]["instructions"]
        assert any("hook_data" in i for i in instructions)


class TestEventBus:
    def test_emits_chat_complete(self):
        mock_bus = MagicMock()
        agent = NaruAgent(
            model="test-model",
            event_bus=mock_bus,
        )

        mock_result = _make_agno_result()
        with patch("naru_agent.agent.AgnoAgent") as MockAgnoAgent:
            mock_agno = MagicMock()
            mock_agno.run.return_value = mock_result
            MockAgnoAgent.return_value = mock_agno

            with patch.object(agent, "_get_agno_model", return_value=MagicMock()):
                agent.chat("test")

        mock_bus.emit.assert_called_once()
        assert mock_bus.emit.call_args[0][0] == "chat_complete"


class TestSessionSupport:
    def test_session_id_passed_to_agno_run(self):
        agent = NaruAgent(model="test-model")
        mock_result = _make_agno_result()

        with patch("naru_agent.agent.AgnoAgent") as MockAgnoAgent:
            mock_agno = MagicMock()
            mock_agno.run.return_value = mock_result
            MockAgnoAgent.return_value = mock_agno

            with patch.object(agent, "_get_agno_model", return_value=MagicMock()):
                result = agent.chat("hi", session_id="sess_123")

        run_kwargs = mock_agno.run.call_args[1]
        assert run_kwargs["session_id"] == "sess_123"
        assert result.session_id == "sess_123"

    def test_no_session_id_not_passed(self):
        agent = NaruAgent(model="test-model")
        mock_result = _make_agno_result()

        with patch("naru_agent.agent.AgnoAgent") as MockAgnoAgent:
            mock_agno = MagicMock()
            mock_agno.run.return_value = mock_result
            MockAgnoAgent.return_value = mock_agno

            with patch.object(agent, "_get_agno_model", return_value=MagicMock()):
                result = agent.chat("hi")

        run_kwargs = mock_agno.run.call_args[1]
        assert "session_id" not in run_kwargs
        assert result.session_id is None

    def test_db_passed_to_agno_agent(self):
        mock_db = MagicMock()
        agent = NaruAgent(model="test-model", db=mock_db, add_history_to_context=True)
        mock_result = _make_agno_result()

        with patch("naru_agent.agent.AgnoAgent") as MockAgnoAgent:
            mock_agno = MagicMock()
            mock_agno.run.return_value = mock_result
            MockAgnoAgent.return_value = mock_agno

            with patch.object(agent, "_get_agno_model", return_value=MagicMock()):
                agent.chat("hi")

        agent_kwargs = MockAgnoAgent.call_args[1]
        assert agent_kwargs["db"] is mock_db
        assert agent_kwargs["add_history_to_context"] is True

    def test_auto_creates_inmemorydb(self):
        with patch("naru_agent.agent.AgnoAgent"):
            agent = NaruAgent(model="test-model", add_history_to_context=True)

        assert agent.db is not None
        # Should be an InMemoryDb instance
        from agno.db.in_memory import InMemoryDb
        assert isinstance(agent.db, InMemoryDb)

    def test_no_db_by_default(self):
        agent = NaruAgent(model="test-model")
        assert agent.db is None

    def test_compression_params_passed(self):
        mock_cm = MagicMock()
        agent = NaruAgent(
            model="test-model",
            compress_tool_results=True,
            compression_manager=mock_cm,
        )
        mock_result = _make_agno_result()

        with patch("naru_agent.agent.AgnoAgent") as MockAgnoAgent:
            mock_agno = MagicMock()
            mock_agno.run.return_value = mock_result
            MockAgnoAgent.return_value = mock_agno

            with patch.object(agent, "_get_agno_model", return_value=MagicMock()):
                agent.chat("hi")

        agent_kwargs = MockAgnoAgent.call_args[1]
        assert agent_kwargs["compress_tool_results"] is True
        assert agent_kwargs["compression_manager"] is mock_cm

    def test_session_summaries_passed(self):
        agent = NaruAgent(model="test-model", enable_session_summaries=True)
        mock_result = _make_agno_result()

        with patch("naru_agent.agent.AgnoAgent") as MockAgnoAgent:
            mock_agno = MagicMock()
            mock_agno.run.return_value = mock_result
            MockAgnoAgent.return_value = mock_agno

            with patch.object(agent, "_get_agno_model", return_value=MagicMock()):
                agent.chat("hi")

        agent_kwargs = MockAgnoAgent.call_args[1]
        assert agent_kwargs["enable_session_summaries"] is True

    def test_blocked_result_has_session_id(self):
        agent = NaruAgent(
            model="test-model",
            guardrails=[BlockGuardrail()],
        )
        with patch.object(agent, "_get_agno_model"):
            result = agent.chat("please block this", session_id="sess_abc")
        assert result.blocked is True
        assert result.session_id == "sess_abc"
