"""Tests for AgentFanout — parallel fan-out primitive."""

from unittest.mock import MagicMock

import pytest

from naru_agent.agent import NaruResult
from naru_agent.orchestration.fanout import AgentFanout


def _make_delegate(content: str) -> MagicMock:
    delegate = MagicMock()
    delegate.chat.return_value = NaruResult(content=content)
    return delegate


class TestFanoutParallelExecution:
    """All agents are called with the same message."""

    def test_all_agents_called(self):
        agents = [_make_delegate("a"), _make_delegate("b"), _make_delegate("c")]
        fanout = AgentFanout(agents)
        fanout.chat("hello")

        for agent in agents:
            agent.chat.assert_called_once_with("hello", None, None)

    def test_all_agents_receive_same_message(self):
        agents = [_make_delegate("x"), _make_delegate("y")]
        fanout = AgentFanout(agents)
        fanout.chat("query", user_id="u1", session_id="s1")

        for agent in agents:
            agent.chat.assert_called_once_with("query", "u1", "s1")


class TestFanoutDefaultMerge:
    """Default merge concatenates content with separator."""

    def test_default_merge_joins_with_separator(self):
        agents = [_make_delegate("result A"), _make_delegate("result B")]
        fanout = AgentFanout(agents)
        result = fanout.chat("query")

        assert result.content == "result A\n\n---\n\nresult B"

    def test_default_merge_skips_empty_content(self):
        agents = [_make_delegate("result A"), _make_delegate(""), _make_delegate("result C")]
        fanout = AgentFanout(agents)
        result = fanout.chat("query")

        assert result.content == "result A\n\n---\n\nresult C"


class TestFanoutCustomMerge:
    """Custom merge function is used when provided."""

    def test_custom_merge(self):
        agents = [_make_delegate("a"), _make_delegate("b")]
        fanout = AgentFanout(
            agents,
            merge=lambda results: NaruResult(content="+".join(r.content for r in results)),
        )
        result = fanout.chat("query")

        assert result.content == "a+b"


class TestFanoutSingleAgent:
    """Single agent = passthrough."""

    def test_single_agent_passthrough(self):
        agent = _make_delegate("only result")
        fanout = AgentFanout([agent])
        result = fanout.chat("query")

        assert result.content == "only result"


class TestFanoutPreservesOrder:
    """Results are ordered by agent index, not completion order."""

    def test_results_in_original_order(self):
        import time

        def slow_chat(msg, user_id=None, session_id=None):
            time.sleep(0.05)
            return NaruResult(content="slow")

        def fast_chat(msg, user_id=None, session_id=None):
            return NaruResult(content="fast")

        slow_agent = MagicMock()
        slow_agent.chat.side_effect = slow_chat
        fast_agent = MagicMock()
        fast_agent.chat.side_effect = fast_chat

        fanout = AgentFanout([slow_agent, fast_agent])
        result = fanout.chat("query")

        # slow is first in the agents list, so should be first in merged output
        assert result.content == "slow\n\n---\n\nfast"


class TestFanoutEmptyRaises:
    """Empty agents list should raise ValueError."""

    def test_empty_agents_raises(self):
        with pytest.raises(ValueError, match="at least one agent"):
            AgentFanout([])


class TestFanoutAsDelegate:
    """Fanout satisfies AgentChatDelegate."""

    def test_name_attribute(self):
        fanout = AgentFanout([_make_delegate("x")], name="my_fanout")
        assert fanout.name == "my_fanout"

    def test_default_name(self):
        fanout = AgentFanout([_make_delegate("x")])
        assert fanout.name == "fanout"
