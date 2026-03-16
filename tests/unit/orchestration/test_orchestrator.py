"""@ac2, @ac10, @ac12 — AgentOrchestrator core tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from naru_agent.agent import NaruResult
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
from naru_agent.orchestration.trace import OrchestrationTimings

import re


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_delegate(content: str = "hi") -> MagicMock:
    delegate = MagicMock()
    delegate.chat.return_value = NaruResult(content=content, session_id="s1")
    return delegate


# ---------------------------------------------------------------------------
# @ac2 — Single-agent zero-overhead passthrough
# ---------------------------------------------------------------------------


class TestOrchestratorPassthrough:
    """@ac2 — minimal orchestrator with no optional features."""

    def test_returns_orchestration_result(self):
        delegate = _mock_delegate("hello")
        orch = AgentOrchestrator(AgentOrchestratorConfig(delegate=delegate))
        result = orch.chat("hi")
        assert isinstance(result, OrchestrationResult)

    def test_content_matches_delegate(self):
        delegate = _mock_delegate("delegate-response")
        orch = AgentOrchestrator(AgentOrchestratorConfig(delegate=delegate))
        result = orch.chat("test")
        assert result.content == "delegate-response"

    def test_delegate_called_with_message(self):
        delegate = _mock_delegate()
        orch = AgentOrchestrator(AgentOrchestratorConfig(delegate=delegate))
        orch.chat("my message", user_id="u1", session_id="s1")
        delegate.chat.assert_called_once_with("my message", user_id="u1", session_id="s1")

    def test_phase_reached_is_delegate(self):
        delegate = _mock_delegate()
        orch = AgentOrchestrator(AgentOrchestratorConfig(delegate=delegate))
        result = orch.chat("hi")
        assert result.decision_trace.phase_reached == "delegate"

    def test_delegate_used_is_default(self):
        delegate = _mock_delegate()
        orch = AgentOrchestrator(AgentOrchestratorConfig(delegate=delegate))
        result = orch.chat("hi")
        assert result.decision_trace.delegate_used == "default"

    def test_orchestrator_satisfies_agent_chat_delegate(self):
        """AgentOrchestrator itself is nestable as a delegate."""
        inner_delegate = _mock_delegate("inner")
        inner_orch = AgentOrchestrator(AgentOrchestratorConfig(delegate=inner_delegate))

        # Use inner_orch as delegate for outer
        outer_delegate = inner_orch
        outer_orch = AgentOrchestrator(AgentOrchestratorConfig(delegate=outer_delegate))
        result = outer_orch.chat("nested")
        assert isinstance(result, OrchestrationResult)


# ---------------------------------------------------------------------------
# @ac10 — AgentDecisionTrace completeness
# ---------------------------------------------------------------------------


class TestDecisionTrace:
    """@ac10 — every result carries a complete AgentDecisionTrace."""

    def test_trace_has_trace_id(self):
        delegate = _mock_delegate()
        orch = AgentOrchestrator(AgentOrchestratorConfig(delegate=delegate))
        result = orch.chat("hi")
        assert result.decision_trace.trace_id is not None
        assert len(result.decision_trace.trace_id) == 36  # UUID4

    def test_trace_has_timings_total(self):
        delegate = _mock_delegate()
        orch = AgentOrchestrator(AgentOrchestratorConfig(delegate=delegate))
        result = orch.chat("hi")
        assert result.decision_trace.timings.total >= 0

    def test_trace_intent_resolved_is_none_without_resolver(self):
        delegate = _mock_delegate()
        orch = AgentOrchestrator(AgentOrchestratorConfig(delegate=delegate))
        result = orch.chat("hi")
        assert result.decision_trace.intent_resolved is None

    def test_trace_records_intent_when_resolver_present(self):
        delegate = _mock_delegate()
        resolver = DeterministicIntentResolver(
            [DeterministicPattern(pattern=re.compile(r"hello"), intent=OrchestratorIntent(object="greeting", confidence=1.0))]
        )
        orch = AgentOrchestrator(AgentOrchestratorConfig(delegate=delegate, intent_resolver=resolver))
        result = orch.chat("hello world")
        assert result.decision_trace.intent_resolved is not None
        assert result.decision_trace.intent_resolved.object == "greeting"


# ---------------------------------------------------------------------------
# @ac12 — Intent-to-delegate routing
# ---------------------------------------------------------------------------


class TestDelegateRouting:
    """@ac12 — named delegates are routed by intent.object."""

    def test_routes_to_named_delegate(self):
        default_delegate = _mock_delegate("default")
        query_delegate = _mock_delegate("query-response")

        resolver = DeterministicIntentResolver(
            [DeterministicPattern(pattern=re.compile(r"search"), intent=OrchestratorIntent(object="query", confidence=0.9))]
        )
        config = AgentOrchestratorConfig(
            delegate=default_delegate,
            delegates={"query": query_delegate},
            intent_resolver=resolver,
        )
        orch = AgentOrchestrator(config)
        result = orch.chat("please search for cats")
        assert result.content == "query-response"
        assert result.decision_trace.delegate_used == "query"

    def test_fallback_to_default_when_no_match(self):
        default_delegate = _mock_delegate("default-response")
        other_delegate = _mock_delegate("other")

        resolver = DeterministicIntentResolver(
            [DeterministicPattern(pattern=re.compile(r"greet"), intent=OrchestratorIntent(object="greeting", confidence=1.0))]
        )
        config = AgentOrchestratorConfig(
            delegate=default_delegate,
            delegates={"other": other_delegate},
            intent_resolver=resolver,
        )
        orch = AgentOrchestrator(config)
        result = orch.chat("hello there")  # matches greeting, not "other"
        # "greeting" not in delegates → falls back to default
        assert result.content == "default-response"

    def test_no_delegates_dict_uses_default(self):
        default_delegate = _mock_delegate("default")
        resolver = DeterministicIntentResolver(
            [DeterministicPattern(pattern=re.compile(r".*"), intent=OrchestratorIntent(object="query", confidence=1.0))]
        )
        config = AgentOrchestratorConfig(delegate=default_delegate, intent_resolver=resolver)
        orch = AgentOrchestrator(config)
        result = orch.chat("anything")
        assert result.content == "default"
