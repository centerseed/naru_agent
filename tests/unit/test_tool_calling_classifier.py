"""Tests for ToolCallingClassifier."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from naru_agent.intent.tool_calling_classifier import (
    LLMToolCallingClassifier,
    ToolCallingResult,
)
from naru_agent.tools.base import BaseTool


# ── Helpers ──────────────────────────────────────────────────────────


class DummyTool(BaseTool):
    def __init__(self, name: str = "get_weather", description: str = "Get weather"):
        self.name = name
        self.description = description
        self.args_schema = None

    def run(self, **kwargs) -> str:
        return f"sunny in {kwargs.get('city', 'unknown')}"


class FailingTool(BaseTool):
    def __init__(self):
        self.name = "failing_tool"
        self.description = "Always fails"
        self.args_schema = None

    def run(self, **kwargs) -> str:
        raise RuntimeError("boom")


def _make_litellm_response(tool_calls=None, content="", usage=None):
    """Build a mock litellm response."""
    msg = SimpleNamespace(
        content=content,
        tool_calls=tool_calls or [],
    )
    choice = SimpleNamespace(message=msg)
    u = SimpleNamespace(
        prompt_tokens=(usage or {}).get("input", 10),
        completion_tokens=(usage or {}).get("output", 5),
        total_tokens=(usage or {}).get("total", 15),
    )
    return SimpleNamespace(choices=[choice], usage=u)


def _make_tool_call(name: str, arguments: str = "{}"):
    fn = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(function=fn)


# ── Tests ────────────────────────────────────────────────────────────


class TestLLMToolCallingClassifier:
    def test_classify_with_tool_calls(self):
        """LLM returns tool_calls → tools are executed, results returned."""
        tool = DummyTool()
        tc = _make_tool_call("get_weather", '{"city": "Taipei"}')
        mock_resp = _make_litellm_response(tool_calls=[tc])

        classifier = LLMToolCallingClassifier()
        with patch("litellm.completion", return_value=mock_resp):
            result = classifier.classify("What's the weather in Taipei?", [tool])

        assert len(result.tool_results) == 1
        assert result.tool_results[0]["tool"] == "get_weather"
        assert "Taipei" in result.tool_results[0]["result"]
        assert result.usage["prompt_tokens"] == 10

    def test_classify_no_tool_calls(self):
        """LLM returns no tool_calls → empty results."""
        tool = DummyTool()
        mock_resp = _make_litellm_response(content="No tools needed")

        classifier = LLMToolCallingClassifier()
        with patch("litellm.completion", return_value=mock_resp):
            result = classifier.classify("Hello!", [tool])

        assert result.tool_results == []
        assert result.raw_response == "No tools needed"
        assert result.usage["total_tokens"] == 15

    def test_classify_error_fallback(self):
        """LLM call fails → returns empty ToolCallingResult gracefully."""
        tool = DummyTool()
        classifier = LLMToolCallingClassifier()
        with patch("litellm.completion", side_effect=Exception("API error")):
            result = classifier.classify("test", [tool])

        assert result.tool_results == []
        assert result.usage == {}

    def test_classify_tool_execution_error(self):
        """Tool execution fails → error message in result, doesn't crash."""
        tool = FailingTool()
        tc = _make_tool_call("failing_tool")
        mock_resp = _make_litellm_response(tool_calls=[tc])

        classifier = LLMToolCallingClassifier()
        with patch("litellm.completion", return_value=mock_resp):
            result = classifier.classify("do something", [tool])

        assert len(result.tool_results) == 1
        assert "Error" in result.tool_results[0]["result"]

    def test_classify_unknown_tool_skipped(self):
        """LLM calls a tool not in the list → skipped."""
        tool = DummyTool()
        tc = _make_tool_call("nonexistent_tool")
        mock_resp = _make_litellm_response(tool_calls=[tc])

        classifier = LLMToolCallingClassifier()
        with patch("litellm.completion", return_value=mock_resp):
            result = classifier.classify("test", [tool])

        assert result.tool_results == []

    def test_classify_multiple_tool_calls(self):
        """LLM calls multiple tools → all executed."""
        tool_a = DummyTool(name="get_weather", description="Get weather")
        tool_b = DummyTool(name="get_time", description="Get time")
        tool_b.run = lambda **kw: "14:00"

        tc_a = _make_tool_call("get_weather", '{"city": "Tokyo"}')
        tc_b = _make_tool_call("get_time")
        mock_resp = _make_litellm_response(tool_calls=[tc_a, tc_b])

        classifier = LLMToolCallingClassifier()
        with patch("litellm.completion", return_value=mock_resp):
            result = classifier.classify("Weather and time?", [tool_a, tool_b])

        assert len(result.tool_results) == 2


class TestIntegrationWithNaruAgent:
    """Test that NaruAgent correctly uses tool_calling_classifier."""

    def test_tool_results_injected_and_tools_stripped(self):
        """When classifier returns results, main agent should not carry tools."""
        from unittest.mock import ANY

        from naru_agent.agent import NaruAgent
        from naru_agent.intent.base import IntentResult

        # Mock classifier
        mock_classifier = MagicMock()
        mock_classifier.classify.return_value = ToolCallingResult(
            tool_results=[{"tool": "get_weather", "args": {}, "result": "sunny"}],
            usage={"input": 10, "output": 5, "total": 15},
        )

        # Mock intent classifier that says needs_tools=True
        mock_intent = MagicMock()
        mock_intent.classify.return_value = IntentResult(
            needs_knowledge=False, needs_tools=True, raw="NY"
        )

        tool = DummyTool()

        agent = NaruAgent(
            model="gemini/gemini-2.5-flash-lite",
            tools=[tool],
            intent_classifier=mock_intent,
            tool_calling_classifier=mock_classifier,
        )

        # Mock the Agno agent run to capture what instructions/tools it gets
        mock_agno = MagicMock()
        mock_agno.run.return_value = SimpleNamespace(
            content="It's sunny!",
            messages=[],
            metrics=SimpleNamespace(input_tokens=50, output_tokens=20),
        )
        agent._agno_agent = mock_agno

        result = agent.chat("What's the weather?")

        # Classifier was called
        mock_classifier.classify.assert_called_once()

        # Main agent got tool results in instructions
        instructions_set = mock_agno.instructions
        assert any("Tool Results" in i for i in instructions_set)
        assert any("sunny" in i for i in instructions_set)

        # Main agent tools should be empty (no tool schemas sent)
        assert mock_agno.tools is None or mock_agno.tools == []
