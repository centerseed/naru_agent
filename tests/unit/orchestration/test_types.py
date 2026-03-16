"""@ac11 — Generic typing verification."""

from __future__ import annotations

from typing import Generic, TypeVar, get_args, get_origin

import pytest

from naru_agent.orchestration.intent import OrchestratorIntent, DeterministicIntentResolver, DeterministicPattern, BaseIntentResolver
from naru_agent.orchestration.orchestrator import AgentOrchestrator, AgentOrchestratorConfig

import re

T = TypeVar("T", bound=str)


class TestGenericTyping:
    """@ac11 — TypeVar + Generic used correctly throughout."""

    def test_orchestrator_intent_is_generic(self):
        """OrchestratorIntent can be instantiated with any str subtype."""
        intent: OrchestratorIntent[str] = OrchestratorIntent(object="greeting", confidence=1.0)
        assert intent.object == "greeting"

    def test_deterministic_resolver_is_generic(self):
        patterns: list[DeterministicPattern[str]] = [
            DeterministicPattern(pattern=re.compile(r"hello"), intent=OrchestratorIntent(object="greeting", confidence=1.0))
        ]
        resolver: BaseIntentResolver[str] = DeterministicIntentResolver(patterns)
        assert resolver is not None

    def test_orchestrator_is_generic(self):
        """AgentOrchestrator[T] can be typed with a specific literal union."""
        from unittest.mock import MagicMock
        from naru_agent.agent import NaruResult

        delegate = MagicMock()
        delegate.chat.return_value = NaruResult(content="hi")
        orch: AgentOrchestrator[str] = AgentOrchestrator(AgentOrchestratorConfig(delegate=delegate))
        result = orch.chat("hello")
        assert result is not None

    def test_orchestrator_config_is_generic(self):
        from unittest.mock import MagicMock
        from naru_agent.agent import NaruResult

        delegate = MagicMock()
        delegate.chat.return_value = NaruResult(content="hi")
        config: AgentOrchestratorConfig[str] = AgentOrchestratorConfig(delegate=delegate)
        assert config.delegate is delegate

    def test_intent_confidence_is_float(self):
        intent = OrchestratorIntent(object="query", confidence=0.75)
        assert isinstance(intent.confidence, float)

    def test_requires_confirmation_defaults_false(self):
        intent = OrchestratorIntent(object="action", confidence=0.9)
        assert intent.requires_confirmation is False
