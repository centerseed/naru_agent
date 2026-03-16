"""@ac9 — Session state entity tracking."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from naru_agent.agent import NaruResult
from naru_agent.orchestration.orchestrator import AgentOrchestrator, AgentOrchestratorConfig
from naru_agent.orchestration.session_state import (
    AgentSessionState,
    InMemorySessionStateStore,
)


class TestInMemorySessionStateStore:
    """@ac9 — session state CRUD operations."""

    def test_save_and_get(self):
        store = InMemorySessionStateStore()
        state = AgentSessionState(session_id="s1", last_presented_entities=["item-a"])
        store.save("s1", state)
        assert store.get("s1") is state

    def test_get_missing_returns_none(self):
        store = InMemorySessionStateStore()
        assert store.get("nonexistent") is None

    def test_clear_removes_state(self):
        store = InMemorySessionStateStore()
        store.save("s1", AgentSessionState(session_id="s1"))
        store.clear("s1")
        assert store.get("s1") is None

    def test_save_overwrites_previous(self):
        store = InMemorySessionStateStore()
        state1 = AgentSessionState(session_id="s1", last_presented_entities=["a"])
        state2 = AgentSessionState(session_id="s1", last_presented_entities=["b"])
        store.save("s1", state1)
        store.save("s1", state2)
        assert store.get("s1").last_presented_entities == ["b"]

    def test_multiple_sessions_independent(self):
        store = InMemorySessionStateStore()
        store.save("s1", AgentSessionState(session_id="s1"))
        store.save("s2", AgentSessionState(session_id="s2"))
        store.clear("s1")
        assert store.get("s2") is not None

    def test_agent_session_state_defaults(self):
        state = AgentSessionState(session_id="s1")
        assert state.last_presented_entities == []
        assert state.metadata == {}
        assert state.updated_at > 0

    def test_metadata_stored(self):
        store = InMemorySessionStateStore()
        state = AgentSessionState(session_id="s1", metadata={"user_lang": "zh"})
        store.save("s1", state)
        assert store.get("s1").metadata["user_lang"] == "zh"


class TestOrchestratorSessionStateSave:
    """@ac9 — Orchestrator saves session state after delegate response."""

    def test_session_state_saved_after_delegate_response(self):
        """Verify orchestrator.chat() persists session state to store."""
        store = InMemorySessionStateStore()
        delegate = MagicMock()
        delegate.chat.return_value = NaruResult(
            content="Hello!",
            blocked=False,
            session_id="sess-1",
        )

        config = AgentOrchestratorConfig(
            delegate=delegate,
            session_state_store=store,
        )
        orch = AgentOrchestrator(config)
        orch.chat("hello", session_id="sess-1")

        saved = store.get("sess-1")
        assert saved is not None
        assert saved.session_id == "sess-1"
        assert saved.last_presented_entities == []
        assert saved.updated_at > 0

    def test_session_state_not_saved_without_session_id(self):
        """No session state save when session_id is not provided."""
        store = InMemorySessionStateStore()
        delegate = MagicMock()
        delegate.chat.return_value = NaruResult(content="Hi", blocked=False)

        config = AgentOrchestratorConfig(
            delegate=delegate,
            session_state_store=store,
        )
        orch = AgentOrchestrator(config)
        orch.chat("hello")

        # No session_id means no state should be saved
        assert store.get("default") is None
