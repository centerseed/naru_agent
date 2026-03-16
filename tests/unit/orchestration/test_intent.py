"""@ac3, @ac4 — DeterministicIntentResolver and LLMFallbackIntentResolver."""

from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest

from naru_agent.agent import NaruResult
from naru_agent.orchestration.intent import (
    DeterministicIntentResolver,
    DeterministicPattern,
    IntentResolveInput,
    LLMFallbackIntentResolver,
    OrchestratorIntent,
)


# ---------------------------------------------------------------------------
# @ac3 — DeterministicIntentResolver
# ---------------------------------------------------------------------------


class TestDeterministicIntentResolver:
    """@ac3 — fast pattern matching, no LLM calls."""

    def test_matches_first_pattern(self):
        resolver = DeterministicIntentResolver(
            [
                DeterministicPattern(pattern=re.compile(r"hello|hi"), intent=OrchestratorIntent(object="greeting", confidence=1.0)),
                DeterministicPattern(pattern=re.compile(r"buy"), intent=OrchestratorIntent(object="action", confidence=0.9)),
            ]
        )
        result = resolver.resolve(IntentResolveInput(message="hello there"))
        assert result.object == "greeting"
        assert result.confidence == 1.0

    def test_returns_unknown_when_no_match(self):
        resolver = DeterministicIntentResolver(
            [DeterministicPattern(pattern=re.compile(r"hello"), intent=OrchestratorIntent(object="greeting", confidence=1.0))]
        )
        result = resolver.resolve(IntentResolveInput(message="random message"))
        assert result.object == "unknown"
        assert result.confidence == 0.0

    def test_empty_patterns_returns_unknown(self):
        resolver = DeterministicIntentResolver([])
        result = resolver.resolve(IntentResolveInput(message="anything"))
        assert result.object == "unknown"

    def test_requires_confirmation_preserved(self):
        resolver = DeterministicIntentResolver(
            [
                DeterministicPattern(
                    pattern=re.compile(r"delete"),
                    intent=OrchestratorIntent(object="action", confidence=0.95, requires_confirmation=True),
                )
            ]
        )
        result = resolver.resolve(IntentResolveInput(message="please delete my account"))
        assert result.requires_confirmation is True


# ---------------------------------------------------------------------------
# @ac4 — LLMFallbackIntentResolver
# ---------------------------------------------------------------------------


class TestLLMFallbackIntentResolver:
    """@ac4 — uses deterministic first, falls back to LLM on 'unknown'."""

    def _make_resolver(self, llm_content: str, parse_response=None):
        primary = DeterministicIntentResolver(
            [DeterministicPattern(pattern=re.compile(r"hello"), intent=OrchestratorIntent(object="greeting", confidence=1.0))]
        )
        mock_agent = MagicMock()
        mock_agent.chat.return_value = MagicMock(content=llm_content)
        return LLMFallbackIntentResolver(
            primary=primary,
            fallback_agent=mock_agent,
            parse_response=parse_response,
        ), mock_agent

    def test_primary_match_skips_llm(self):
        resolver, mock_agent = self._make_resolver('{"object":"unused","confidence":0}')
        result = resolver.resolve(IntentResolveInput(message="hello world"))
        assert result.object == "greeting"
        mock_agent.chat.assert_not_called()

    def test_unknown_triggers_llm_fallback(self):
        resolver, mock_agent = self._make_resolver('{"object":"query","confidence":0.8}')
        result = resolver.resolve(IntentResolveInput(message="what is the weather"))
        mock_agent.chat.assert_called_once()
        assert result.object == "query"
        assert result.confidence == pytest.approx(0.8)

    def test_invalid_llm_json_returns_unknown(self):
        resolver, _ = self._make_resolver("not json at all")
        result = resolver.resolve(IntentResolveInput(message="something weird"))
        assert result.object == "unknown"
        assert result.confidence == 0.0

    def test_custom_parse_response_called(self):
        custom_result = OrchestratorIntent(object="custom", confidence=0.99)
        parse_fn = MagicMock(return_value=custom_result)
        resolver, _ = self._make_resolver('{"object":"ignored"}', parse_response=parse_fn)
        result = resolver.resolve(IntentResolveInput(message="parse this please"))
        parse_fn.assert_called_once()
        assert result.object == "custom"
