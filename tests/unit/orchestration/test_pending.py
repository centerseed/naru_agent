"""@ac6, @ac7 — PendingStateManager and confirmation disposition classifier."""

from __future__ import annotations

import pytest

from naru_agent.agent import NaruResult
from naru_agent.orchestration.orchestrator import (
    AgentOrchestrator,
    AgentOrchestratorConfig,
)
from naru_agent.orchestration.pending import (
    InMemoryPendingStateManager,
    PendingState,
    classify_confirmation_disposition,
)
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# @ac7 — classify_confirmation_disposition
# ---------------------------------------------------------------------------


class TestClassifyConfirmationDisposition:
    """@ac7 — CJK + English confirmation patterns."""

    @pytest.mark.parametrize("msg", ["yes", "YES", "y", "Y", "ok", "OK", "sure", "confirm", "好", "確認", "對", "好的", "是", "沒問題"])
    def test_confirm_words(self, msg):
        assert classify_confirmation_disposition(msg) == "confirm"

    @pytest.mark.parametrize("msg", ["no", "NO", "n", "N", "cancel", "reject", "不要", "取消", "不", "否", "算了", "不行"])
    def test_reject_words(self, msg):
        assert classify_confirmation_disposition(msg) == "reject"

    @pytest.mark.parametrize("msg", ["maybe later", "tell me more", "what exactly", ""])
    def test_override_words(self, msg):
        assert classify_confirmation_disposition(msg) == "override"

    def test_strips_whitespace(self):
        assert classify_confirmation_disposition("  yes  ") == "confirm"


# ---------------------------------------------------------------------------
# @ac6 — InMemoryPendingStateManager + orchestration flow
# ---------------------------------------------------------------------------


class TestInMemoryPendingStateManager:
    """@ac6 — pending state confirmation flow."""

    def test_set_and_get(self):
        mgr = InMemoryPendingStateManager()
        state = PendingState(type="delete", payload={"id": 1})
        mgr.set_pending("sess-1", state)
        assert mgr.get_pending("sess-1") is state

    def test_clear_removes_state(self):
        mgr = InMemoryPendingStateManager()
        mgr.set_pending("sess-1", PendingState(type="action"))
        mgr.clear_pending("sess-1")
        assert mgr.get_pending("sess-1") is None

    def test_get_missing_returns_none(self):
        mgr = InMemoryPendingStateManager()
        assert mgr.get_pending("nonexistent") is None


class TestOrchestratorPendingConfirmationFlow:
    """@ac6 — orchestrator routes confirm/reject through Phase 0."""

    def _setup(self, session_id: str = "sess-1"):
        mgr = InMemoryPendingStateManager()
        delegate = MagicMock()
        delegate.chat.return_value = NaruResult(content="delegate", session_id=session_id)
        config = AgentOrchestratorConfig(delegate=delegate, pending_state_manager=mgr)
        orch = AgentOrchestrator(config)
        return orch, mgr, delegate

    def test_confirm_resolves_pending(self):
        orch, mgr, delegate = self._setup()
        mgr.set_pending("sess-1", PendingState(type="delete_account"))
        result = orch.chat("yes", session_id="sess-1")
        assert result.decision_trace.phase_reached == "pending_confirmation"
        assert "Confirmed" in result.content
        delegate.chat.assert_not_called()

    def test_reject_resolves_pending(self):
        orch, mgr, delegate = self._setup()
        mgr.set_pending("sess-1", PendingState(type="send_email"))
        result = orch.chat("no", session_id="sess-1")
        assert result.decision_trace.phase_reached == "pending_confirmation"
        assert "Rejected" in result.content

    def test_override_clears_pending_and_continues(self):
        orch, mgr, delegate = self._setup()
        mgr.set_pending("sess-1", PendingState(type="something"))
        result = orch.chat("tell me more about it", session_id="sess-1")
        # override → pending cleared → delegate called
        assert mgr.get_pending("sess-1") is None
        delegate.chat.assert_called_once()
