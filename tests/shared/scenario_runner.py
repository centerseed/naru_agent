"""Shared scenario runner helpers for Python integration tests.

Mirrors the JS scenario-runner.ts — loads shared JSON scenarios from
tests/shared/scenarios/ and provides assertion helpers.

Usage::

    from tests.shared.scenario_runner import load_scenarios, assert_scenario_result

    scenarios = load_scenarios("orchestration.json")
    for s in scenarios["scenarios"]:
        result = orchestrator.chat(s["input"])
        assert_scenario_result(result, s["expect"])
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from naru_agent.agent import NaruResult

SHARED_ROOT = Path(__file__).parent


def load_scenarios(filename: str) -> dict[str, Any]:
    """Load a scenario JSON file from tests/shared/scenarios/.

    Args:
        filename: e.g. "orchestration.json"
    """
    file_path = SHARED_ROOT / "scenarios" / filename
    return json.loads(file_path.read_text(encoding="utf-8"))


def load_baseline() -> dict[str, Any]:
    """Load the shared quality baseline from tests/shared/baselines/."""
    file_path = SHARED_ROOT / "baselines" / "quality_baseline.json"
    return json.loads(file_path.read_text(encoding="utf-8"))


def assert_scenario_result(
    result: NaruResult,
    expect: dict[str, Any],
    baseline: dict[str, Any] | None = None,
) -> None:
    """Validate a NaruResult against a ScenarioExpect definition.

    Mirrors JS assertScenarioResult() from scenario-runner.ts.
    """
    if "blocked" in expect:
        assert result.blocked == expect["blocked"], (
            f"Expected blocked={expect['blocked']}, got {result.blocked}"
        )

    if expect.get("content_not_empty"):
        assert len(result.content) > 0, "Expected non-empty content"

    if "content_keywords_any" in expect:
        content_lower = result.content.lower()
        found = any(kw.lower() in content_lower for kw in expect["content_keywords_any"])
        assert found, (
            f"Expected content to contain any of {expect['content_keywords_any']}, "
            f"got: {result.content!r}"
        )

    if "content_keywords_all" in expect:
        content_lower = result.content.lower()
        for kw in expect["content_keywords_all"]:
            assert kw.lower() in content_lower, (
                f"Expected content to contain {kw!r}, got: {result.content!r}"
            )

    if "toolCalls_contains" in expect:
        for tool in expect["toolCalls_contains"]:
            assert tool in result.tool_calls, (
                f"Expected tool_calls to contain {tool!r}, got: {result.tool_calls}"
            )

    if "toolCalls_contains_any" in expect:
        found = any(tool in result.tool_calls for tool in expect["toolCalls_contains_any"])
        assert found, (
            f"Expected tool_calls to contain any of {expect['toolCalls_contains_any']}, "
            f"got: {result.tool_calls}"
        )

    if "toolCalls_not_contains" in expect:
        for tool in expect["toolCalls_not_contains"]:
            assert tool not in result.tool_calls, (
                f"Expected tool_calls NOT to contain {tool!r}, got: {result.tool_calls}"
            )

    if "toolCalls_max_count" in expect:
        assert len(result.tool_calls) <= expect["toolCalls_max_count"], (
            f"Expected at most {expect['toolCalls_max_count']} tool calls, "
            f"got {len(result.tool_calls)}"
        )

    if "toolCalls_min_count" in expect:
        assert len(result.tool_calls) >= expect["toolCalls_min_count"], (
            f"Expected at least {expect['toolCalls_min_count']} tool calls, "
            f"got {len(result.tool_calls)}"
        )

    if "tokens_max" in expect:
        max_tokens = expect["tokens_max"]
        if isinstance(max_tokens, str):
            if baseline is None:
                raise ValueError(
                    f'tokens_max references baseline key "{max_tokens}" '
                    "but no baseline was provided"
                )
            max_tokens = baseline[max_tokens]
        total = result.usage.get("total_tokens", result.usage.get("totalTokens", 0))
        assert total <= max_tokens, (
            f"Expected at most {max_tokens} tokens, got {total}"
        )
