"""Tests for intent classification."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from naru_agent.intent.base import BaseIntentClassifier, IntentResult
from naru_agent.intent.llm_classifier import LLMIntentClassifier


class TestIntentResult:
    def test_defaults(self):
        r = IntentResult()
        assert r.needs_knowledge is True
        assert r.needs_tools is True
        assert r.raw == ""


class TestParseResponse:
    @pytest.mark.parametrize(
        "raw, knowledge, tools",
        [
            ("YY", True, True),
            ("YN", True, False),
            ("NY", False, True),
            ("NN", False, False),
            ("yy", True, True),
            ("  YN  ", True, False),
            ("`YY`", True, True),
            ("```NN```", False, False),
        ],
    )
    def test_valid_codes(self, raw, knowledge, tools):
        result = LLMIntentClassifier._parse_response(raw)
        assert result.needs_knowledge is knowledge
        assert result.needs_tools is tools

    def test_malformed_defaults_to_true(self):
        result = LLMIntentClassifier._parse_response("")
        assert result.needs_knowledge is True
        assert result.needs_tools is True

    def test_single_char_defaults_to_true(self):
        result = LLMIntentClassifier._parse_response("Y")
        assert result.needs_knowledge is True
        assert result.needs_tools is True

    def test_garbage_defaults_to_true(self):
        result = LLMIntentClassifier._parse_response("hello world")
        assert result.needs_knowledge is True
        assert result.needs_tools is True

    def test_embedded_code_extracted(self):
        # Handles "Answer: YN" case (review comment fix)
        result = LLMIntentClassifier._parse_response("Answer: YN")
        assert result.needs_knowledge is True
        assert result.needs_tools is False
        assert result.raw == "YN"

    def test_verbose_response_with_code(self):
        result = LLMIntentClassifier._parse_response("I think the answer is NN because...")
        assert result.needs_knowledge is False
        assert result.needs_tools is False


class TestLLMIntentClassifier:
    def test_classify_success(self):
        classifier = LLMIntentClassifier(model="test-model")

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "YN"

        with patch("litellm.completion", return_value=mock_resp):
            result = classifier.classify("什麼是乳酸閾值")
            assert result.needs_knowledge is True
            assert result.needs_tools is False

    def test_classify_fallback_on_error(self):
        classifier = LLMIntentClassifier(model="test-model")

        with patch("litellm.completion", side_effect=Exception("API error")):
            result = classifier.classify("test")
            assert result.needs_knowledge is True
            assert result.needs_tools is True
            assert result.raw == "YY"

    def test_custom_examples(self):
        examples = [("hi", "NN"), ("search", "NY")]
        classifier = LLMIntentClassifier(
            model="test-model",
            examples=examples,
        )
        prompt = classifier._build_prompt("hello")
        assert "「hi」→ NN" in prompt
        assert "「search」→ NY" in prompt
        assert "「hello」→" in prompt

    def test_api_key_passed(self):
        classifier = LLMIntentClassifier(
            model="test-model",
            api_key="test-key",
        )

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "NN"

        with patch("litellm.completion", return_value=mock_resp) as mock_call:
            classifier.classify("test")
            call_kwargs = mock_call.call_args[1]
            assert call_kwargs["api_key"] == "test-key"
