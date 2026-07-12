"""_plan_attempts: primary → per-call fallbacks → env fallbacks（去重保序）。

不打真 LLM：_plan_attempts 是純函式，直接測。
"""
import pytest

from naru_agent.llm.async_gateway import _plan_attempts


def test_plan_attempts_without_fallbacks_is_primary_only(monkeypatch):
    monkeypatch.delenv("NARU_LLM_FALLBACK_MODELS", raising=False)
    assert _plan_attempts("mistral/ministral-3b-latest") == ["mistral/ministral-3b-latest"]


def test_per_call_fallbacks_follow_primary(monkeypatch):
    monkeypatch.delenv("NARU_LLM_FALLBACK_MODELS", raising=False)
    ladder = _plan_attempts(
        "mistral/ministral-3b-latest",
        ["mistral/mistral-small-latest", "gemini/gemini-2.5-flash-lite"],
    )
    assert ladder == [
        "mistral/ministral-3b-latest",
        "mistral/mistral-small-latest",
        "gemini/gemini-2.5-flash-lite",
    ]


def test_per_call_fallbacks_precede_env_fallbacks(monkeypatch):
    monkeypatch.setenv("NARU_LLM_FALLBACK_MODELS", "mistral/mistral-small-latest")
    ladder = _plan_attempts("gemini/gemma-4-26b-a4b-it", ["gemini/gemini-2.5-flash-lite"])
    assert ladder == [
        "gemini/gemma-4-26b-a4b-it",
        "gemini/gemini-2.5-flash-lite",
        "mistral/mistral-small-latest",
    ]


def test_duplicates_and_self_are_dropped(monkeypatch):
    monkeypatch.setenv("NARU_LLM_FALLBACK_MODELS", "mistral/mistral-small-latest,gemini/x")
    ladder = _plan_attempts(
        "gemini/x",
        ["mistral/mistral-small-latest", "gemini/x"],
    )
    assert ladder == ["gemini/x", "mistral/mistral-small-latest"]


def test_none_fallbacks_matches_legacy_behaviour(monkeypatch):
    monkeypatch.setenv("NARU_LLM_FALLBACK_MODELS", "mistral/mistral-small-latest")
    assert _plan_attempts("gemini/x", None) == ["gemini/x", "mistral/mistral-small-latest"]
