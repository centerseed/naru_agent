"""@ac13 — Lifecycle hooks."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from naru_agent.agent import NaruResult
from naru_agent.orchestration.orchestrator import (
    AgentOrchestrator,
    AgentOrchestratorConfig,
    LifecycleHooks,
)
from naru_agent.orchestration.result import OrchestrationResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_delegate(content="hi"):
    delegate = MagicMock()
    delegate.chat.return_value = NaruResult(content=content)
    return delegate


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLifecycleHooks:
    """@ac13 — hooks are called at the right moments."""

    def test_before_message_hook_called(self):
        hook = MagicMock()
        delegate = _mock_delegate()
        config = AgentOrchestratorConfig(
            delegate=delegate,
            lifecycle_hooks=LifecycleHooks(before_message=hook),
        )
        orch = AgentOrchestrator(config)
        orch.chat("hello", user_id="u1", session_id="s1")
        hook.assert_called_once_with("hello", "u1", "s1")

    def test_after_message_hook_called_with_result(self):
        hook = MagicMock()
        delegate = _mock_delegate("response")
        config = AgentOrchestratorConfig(
            delegate=delegate,
            lifecycle_hooks=LifecycleHooks(after_message=hook),
        )
        orch = AgentOrchestrator(config)
        orch.chat("hello")
        hook.assert_called_once()
        called_result = hook.call_args[0][0]
        assert isinstance(called_result, OrchestrationResult)
        assert called_result.content == "response"

    def test_on_error_hook_called_on_exception(self):
        error_hook = MagicMock()
        delegate = MagicMock()
        delegate.chat.side_effect = RuntimeError("boom")
        config = AgentOrchestratorConfig(
            delegate=delegate,
            lifecycle_hooks=LifecycleHooks(on_error=error_hook),
        )
        orch = AgentOrchestrator(config)
        with pytest.raises(RuntimeError, match="boom"):
            orch.chat("hello")
        error_hook.assert_called_once()
        assert isinstance(error_hook.call_args[0][0], RuntimeError)

    def test_exception_in_before_hook_does_not_block_flow(self):
        """Hook exceptions are swallowed."""
        def bad_hook(*args):
            raise ValueError("hook error")

        delegate = _mock_delegate("ok")
        config = AgentOrchestratorConfig(
            delegate=delegate,
            lifecycle_hooks=LifecycleHooks(before_message=bad_hook),
        )
        orch = AgentOrchestrator(config)
        result = orch.chat("hello")  # should NOT raise
        assert result.content == "ok"

    def test_exception_in_after_hook_does_not_block_result(self):
        def bad_hook(result):
            raise RuntimeError("after hook error")

        delegate = _mock_delegate("value")
        config = AgentOrchestratorConfig(
            delegate=delegate,
            lifecycle_hooks=LifecycleHooks(after_message=bad_hook),
        )
        orch = AgentOrchestrator(config)
        result = orch.chat("hello")
        assert result.content == "value"

    def test_no_hooks_runs_fine(self):
        """No lifecycle_hooks configured → no error."""
        delegate = _mock_delegate()
        orch = AgentOrchestrator(AgentOrchestratorConfig(delegate=delegate))
        result = orch.chat("hello")
        assert isinstance(result, OrchestrationResult)
