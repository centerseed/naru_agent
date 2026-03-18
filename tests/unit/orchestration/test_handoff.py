"""Tests for AgentHandoffLoop — handoff chain primitive."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from naru_agent.agent import HandoffRequest, NaruResult
from naru_agent.orchestration.handoff import AgentHandoffLoop


def _make_delegate(content: str, handoff: HandoffRequest | None = None) -> MagicMock:
    delegate = MagicMock()
    delegate.chat.return_value = NaruResult(content=content, handoff=handoff)
    return delegate


class TestHandoffSingleHop:
    """A hands off to B, B returns normally."""

    def test_single_handoff(self):
        agent_a = _make_delegate("", handoff=HandoffRequest(target="b", reason="billing"))
        agent_b = _make_delegate("billing response")

        loop = AgentHandoffLoop(
            agents={"a": agent_a, "b": agent_b},
            entry="a",
        )
        result = loop.chat("I have a billing question")

        agent_a.chat.assert_called_once()
        agent_b.chat.assert_called_once()
        assert result.content == "billing response"

    def test_handoff_with_custom_message(self):
        agent_a = _make_delegate(
            "",
            handoff=HandoffRequest(target="b", message="handle billing for user"),
        )
        agent_b = _make_delegate("done")

        loop = AgentHandoffLoop(agents={"a": agent_a, "b": agent_b}, entry="a")
        loop.chat("original message")

        # B should receive the custom handoff message, not the original
        agent_b.chat.assert_called_once_with(
            "handle billing for user", user_id=None, session_id=None,
        )

    def test_handoff_without_custom_message_uses_original(self):
        agent_a = _make_delegate("", handoff=HandoffRequest(target="b"))
        agent_b = _make_delegate("done")

        loop = AgentHandoffLoop(agents={"a": agent_a, "b": agent_b}, entry="a")
        loop.chat("original message")

        # B should receive the original message
        agent_b.chat.assert_called_once_with(
            "original message", user_id=None, session_id=None,
        )


class TestHandoffChain:
    """A → B → C chain."""

    def test_multi_hop(self):
        agent_a = _make_delegate("", handoff=HandoffRequest(target="b"))
        agent_b = _make_delegate("", handoff=HandoffRequest(target="c"))
        agent_c = _make_delegate("final answer")

        loop = AgentHandoffLoop(
            agents={"a": agent_a, "b": agent_b, "c": agent_c},
            entry="a",
        )
        result = loop.chat("question")

        assert result.content == "final answer"
        agent_a.chat.assert_called_once()
        agent_b.chat.assert_called_once()
        agent_c.chat.assert_called_once()


class TestHandoffMaxLimit:
    """Exceeding max_handoffs returns last result with warning."""

    def test_limit_reached(self):
        # Every agent hands off to the next in a cycle
        agent_a = _make_delegate("loop-a", handoff=HandoffRequest(target="b"))
        agent_b = _make_delegate("loop-b", handoff=HandoffRequest(target="a"))

        loop = AgentHandoffLoop(
            agents={"a": agent_a, "b": agent_b},
            entry="a",
            max_handoffs=3,
        )
        result = loop.chat("question")

        # Should return after max_handoffs + 1 iterations
        assert result is not None
        total_calls = agent_a.chat.call_count + agent_b.chat.call_count
        assert total_calls == 4  # max_handoffs + 1


class TestHandoffNoHandoff:
    """Agent returns normally without handoff."""

    def test_no_handoff_returns_directly(self):
        agent = _make_delegate("direct answer")
        loop = AgentHandoffLoop(agents={"main": agent}, entry="main")
        result = loop.chat("question")

        assert result.content == "direct answer"
        assert result.handoff is None
        agent.chat.assert_called_once()


class TestHandoffUnknownAgentRaises:
    """Handoff to unknown agent raises ValueError."""

    def test_unknown_target_raises(self):
        agent_a = _make_delegate("", handoff=HandoffRequest(target="nonexistent"))
        loop = AgentHandoffLoop(agents={"a": agent_a}, entry="a")

        with pytest.raises(ValueError, match="Unknown agent: nonexistent"):
            loop.chat("question")

    def test_unknown_entry_raises(self):
        agent = _make_delegate("x")
        with pytest.raises(ValueError, match="Entry agent 'bad' not found"):
            AgentHandoffLoop(agents={"a": agent}, entry="bad")


class TestHandoffEmptyRaises:
    """Empty agents dict should raise ValueError."""

    def test_empty_agents_raises(self):
        with pytest.raises(ValueError, match="at least one agent"):
            AgentHandoffLoop(agents={}, entry="a")


class TestHandoffPreservesUserIdSessionId:
    """user_id and session_id are forwarded through the chain."""

    def test_forwarding(self):
        agent_a = _make_delegate("", handoff=HandoffRequest(target="b"))
        agent_b = _make_delegate("done")

        loop = AgentHandoffLoop(agents={"a": agent_a, "b": agent_b}, entry="a")
        loop.chat("msg", user_id="u1", session_id="s1")

        agent_a.chat.assert_called_once_with("msg", user_id="u1", session_id="s1")
        agent_b.chat.assert_called_once_with("msg", user_id="u1", session_id="s1")


class TestHandoffAsDelegate:
    """HandoffLoop satisfies AgentChatDelegate."""

    def test_name_attribute(self):
        loop = AgentHandoffLoop(
            agents={"a": _make_delegate("x")},
            entry="a",
            name="my_loop",
        )
        assert loop.name == "my_loop"

    def test_default_name(self):
        loop = AgentHandoffLoop(agents={"a": _make_delegate("x")}, entry="a")
        assert loop.name == "handoff_loop"
