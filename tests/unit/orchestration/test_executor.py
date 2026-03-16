"""@ac5 — BaseDirectExecutor fast-path tests."""

from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest

from naru_agent.orchestration.executor import BaseDirectExecutor
from naru_agent.orchestration.intent import (
    DeterministicIntentResolver,
    DeterministicPattern,
    OrchestratorIntent,
)
from naru_agent.orchestration.orchestrator import (
    AgentOrchestrator,
    AgentOrchestratorConfig,
)
from naru_agent.orchestration.result import OrchestrationResult
from naru_agent.agent import NaruResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class GreetingExecutor(BaseDirectExecutor):
    """Executor that handles greeting intents directly."""

    @property
    def name(self) -> str:
        return "greeting_executor"

    def can_handle(self, intent: OrchestratorIntent) -> bool:
        return intent.object == "greeting"

    def execute(self, *, message, intent, options=None) -> OrchestrationResult | None:
        return OrchestrationResult(content="Hello from executor!")


class PassthroughExecutor(BaseDirectExecutor):
    """Executor that never handles anything (returns None)."""

    @property
    def name(self) -> str:
        return "passthrough_executor"

    def can_handle(self, intent: OrchestratorIntent) -> bool:
        return True

    def execute(self, *, message, intent, options=None) -> OrchestrationResult | None:
        return None  # fallthrough


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBaseDirectExecutor:
    """@ac5 — Direct executor fast-path skips delegate."""

    def _setup(self, executors, intent_object="greeting"):
        delegate = MagicMock()
        delegate.chat.return_value = NaruResult(content="delegate-response")
        resolver = DeterministicIntentResolver(
            [DeterministicPattern(pattern=re.compile(r".*"), intent=OrchestratorIntent(object=intent_object, confidence=1.0))]
        )
        config = AgentOrchestratorConfig(
            delegate=delegate,
            intent_resolver=resolver,
            direct_executors=executors,
        )
        return AgentOrchestrator(config), delegate

    def test_executor_intercepts_before_delegate(self):
        orch, delegate = self._setup([GreetingExecutor()])
        result = orch.chat("hi there")
        assert result.content == "Hello from executor!"
        delegate.chat.assert_not_called()

    def test_phase_is_direct_execution(self):
        orch, _ = self._setup([GreetingExecutor()])
        result = orch.chat("hi")
        assert result.decision_trace.phase_reached == "direct_execution"

    def test_executor_name_recorded_in_trace(self):
        orch, _ = self._setup([GreetingExecutor()])
        result = orch.chat("hi")
        assert result.decision_trace.direct_executor_used == "greeting_executor"

    def test_null_return_falls_through_to_delegate(self):
        orch, delegate = self._setup([PassthroughExecutor()])
        result = orch.chat("test")
        # PassthroughExecutor returns None → falls to delegate
        assert result.content == "delegate-response"
        delegate.chat.assert_called_once()

    def test_no_executor_if_no_intent_resolver(self):
        """Executors are only tried when intent has been resolved."""
        delegate = MagicMock()
        delegate.chat.return_value = NaruResult(content="direct")
        orch = AgentOrchestrator(
            AgentOrchestratorConfig(delegate=delegate, direct_executors=[GreetingExecutor()])
        )
        result = orch.chat("greeting")
        # No intent → executors skipped → delegate called
        assert result.content == "direct"
        delegate.chat.assert_called_once()
