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
        # Agent should be called without tools (set as attribute, not kwarg)
        assert mock_agno.tools is None
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
        # tools and instructions are set as attributes after AgnoAgent creation
        assert mock_agno.tools is not None
        assert any("Knowledge" in i for i in mock_agno.instructions)


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
        # instructions are set as attribute after AgnoAgent creation
        assert any("Memory" in i for i in mock_agno.instructions)

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
        # instructions are set as attribute after AgnoAgent creation
        assert any("hook_data" in i for i in mock_agno.instructions)


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

        emitted_events = [call[0][0] for call in mock_bus.emit.call_args_list]
        assert "chat_complete" in emitted_events


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


class TestFallbackLLMPath:
    @staticmethod
    def _make_empty_result_with_tool_msgs():
        mock_result = MagicMock()
        mock_result.content = ""
        mock_tool_msg = MagicMock()
        mock_tool_msg.role = "tool"
        mock_tool_msg.content = "Tool output data"
        mock_result.messages = [mock_tool_msg]
        mock_result.metrics = MagicMock()
        mock_result.metrics.input_tokens = 10
        mock_result.metrics.output_tokens = 5
        return mock_result

    def test_fallback_called_when_content_empty_after_tool_calls(self):
        """When Agno returns empty content but has tool results, fallback LLM is used."""
        import litellm as real_litellm

        agent = NaruAgent(model="test-model")
        mock_result = self._make_empty_result_with_tool_msgs()

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "Fallback response"

        with patch("naru_agent.agent.AgnoAgent") as MockAgnoAgent:
            mock_agno = MagicMock()
            mock_agno.run.return_value = mock_result
            MockAgnoAgent.return_value = mock_agno

            with patch.object(agent, "_get_agno_model", return_value=MagicMock()):
                with patch("litellm.completion", return_value=mock_resp) as mock_comp:
                    result = agent.chat("test")

        assert result.content == "Fallback response"
        mock_comp.assert_called_once()

    def test_default_message_when_no_tool_results(self):
        """When Agno returns empty content and no tool messages, default message is used."""
        agent = NaruAgent(model="test-model")

        mock_result = MagicMock()
        mock_result.content = ""
        mock_result.messages = []
        mock_result.metrics = MagicMock()
        mock_result.metrics.input_tokens = 10
        mock_result.metrics.output_tokens = 0

        with patch("naru_agent.agent.AgnoAgent") as MockAgnoAgent:
            mock_agno = MagicMock()
            mock_agno.run.return_value = mock_result
            MockAgnoAgent.return_value = mock_agno

            with patch.object(agent, "_get_agno_model", return_value=MagicMock()):
                result = agent.chat("test")

        assert result.content == "抱歉，我剛剛出了一點狀況，可以再說一次嗎？"

    def test_fallback_exception_returns_default_message(self):
        """When fallback LLM throws an exception, default message is returned."""
        agent = NaruAgent(model="test-model")
        mock_result = self._make_empty_result_with_tool_msgs()

        with patch("naru_agent.agent.AgnoAgent") as MockAgnoAgent:
            mock_agno = MagicMock()
            mock_agno.run.return_value = mock_result
            MockAgnoAgent.return_value = mock_agno

            with patch.object(agent, "_get_agno_model", return_value=MagicMock()):
                with patch("litellm.completion", side_effect=Exception("API error")):
                    result = agent.chat("test")

        assert result.content == "抱歉，我剛剛出了一點狀況，可以再說一次嗎？"


# ---------------------------------------------------------------------------
# TestAlwaysTools
# ---------------------------------------------------------------------------


class TestAlwaysTools:
    """Tests for always_tools parameter in _prepare_tools."""

    def _make_dummy_tool(self, name: str = "dummy"):
        from naru_agent.tools.base import tool as tool_decorator

        @tool_decorator(description=f"{name} tool")
        def dummy(x: str) -> str:
            return x

        dummy.__name__ = name
        return dummy

    def test_always_tools_returned_when_needs_tools_false(self):
        """always_tools 有工具、needs_tools=False → _prepare_tools(False) 回傳非空列表"""
        dummy = self._make_dummy_tool()

        with patch("naru_agent.tools.agno_adapter.NaruToolkit") as MockToolkit:
            mock_tk = MagicMock()
            mock_tk.toolkit = MagicMock()
            MockToolkit.return_value = mock_tk

            agent = NaruAgent(model="test-model", always_tools=[dummy])
            result = agent._prepare_tools(needs_tools=False)

        assert len(result) == 1
        MockToolkit.assert_called_once_with([dummy])

    def test_no_always_tools_needs_tools_false_returns_empty(self):
        """always_tools=None、needs_tools=False → 回傳空列表（不迴歸）"""
        agent = NaruAgent(model="test-model")
        result = agent._prepare_tools(needs_tools=False)
        assert result == []

    def test_always_tools_basetool_wrapped_as_narutoolkit(self):
        """always_tools 有 BaseTool → 被正確 wrap 為 NaruToolkit"""
        from naru_agent.tools.base import BaseTool

        dummy = self._make_dummy_tool()
        assert isinstance(dummy, BaseTool)

        with patch("naru_agent.tools.agno_adapter.NaruToolkit") as MockToolkit:
            mock_tk = MagicMock()
            mock_tk.toolkit = object()
            MockToolkit.return_value = mock_tk

            agent = NaruAgent(model="test-model", always_tools=[dummy])
            result = agent._prepare_tools(needs_tools=False)

        MockToolkit.assert_called_once_with([dummy])
        assert result == [mock_tk.toolkit]

    def test_always_tools_appended_alongside_regular_tools(self):
        """needs_tools=True 時，regular tools 與 always_tools 都出現在結果中"""
        read_tool = self._make_dummy_tool("read_tool")
        write_tool = self._make_dummy_tool("write_tool")

        with patch("naru_agent.tools.agno_adapter.NaruToolkit") as MockToolkit:
            toolkit_instances = [MagicMock(), MagicMock()]
            toolkit_instances[0].toolkit = object()
            toolkit_instances[1].toolkit = object()
            MockToolkit.side_effect = toolkit_instances

            agent = NaruAgent(
                model="test-model",
                tools=[read_tool],
                always_tools=[write_tool],
            )
            result = agent._prepare_tools(needs_tools=True)

        assert MockToolkit.call_count == 2
        assert len(result) == 2
