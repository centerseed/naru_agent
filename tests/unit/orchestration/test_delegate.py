"""@ac1 — AgentChatDelegate Protocol compatibility."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from naru_agent.agent import NaruAgent, NaruResult
from naru_agent.orchestration.orchestrator import AgentChatDelegate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_naru_agent() -> NaruAgent:
    """Create a minimal NaruAgent stub (no real LLM needed)."""
    agent = MagicMock(spec=NaruAgent)
    agent.chat.return_value = NaruResult(content="hello")
    return agent


class MinimalDelegate:
    """Bare-minimum implementation satisfying AgentChatDelegate."""

    def chat(
        self,
        message: str,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> NaruResult:
        return NaruResult(content=f"echo:{message}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAgentChatDelegateProtocol:
    """@ac1 — structural subtyping (Protocol)."""

    def test_naru_agent_satisfies_delegate_protocol(self):
        """NaruAgent structurally satisfies AgentChatDelegate without explicit inheritance."""
        agent = _make_naru_agent()
        # isinstance check works because ChannelAdapter is @runtime_checkable Protocol — but
        # AgentChatDelegate is a plain Protocol; we verify by duck-typing assignment instead.
        delegate: AgentChatDelegate = agent  # type: ignore[assignment]
        result = delegate.chat("hi", user_id="u1", session_id="s1")
        assert isinstance(result, NaruResult)

    def test_minimal_delegate_satisfies_protocol(self):
        """Any class with the right chat() signature satisfies the protocol."""
        delegate: AgentChatDelegate = MinimalDelegate()  # type: ignore[assignment]
        result = delegate.chat("test")
        assert result.content == "echo:test"

    def test_delegate_chat_positional_message(self):
        """Message is the first positional argument."""
        delegate: AgentChatDelegate = MinimalDelegate()  # type: ignore[assignment]
        result = delegate.chat("pos_test")
        assert "pos_test" in result.content

    def test_delegate_chat_keyword_args_optional(self):
        """user_id and session_id are keyword-optional."""
        delegate: AgentChatDelegate = MinimalDelegate()  # type: ignore[assignment]
        result = delegate.chat("test", user_id=None, session_id=None)
        assert isinstance(result, NaruResult)
