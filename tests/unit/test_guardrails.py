"""Guardrails 單元測試"""
from __future__ import annotations

import pytest

from naru_agent.guardrails.keyword import KeywordGuardrail


def test_keyword_guardrail_blocks_input():
    guard = KeywordGuardrail(
        blocked_patterns=["處方", "劑量"],
        input_message="抱歉，無法回答醫療問題。",
    )
    result = guard.check_input("這個藥的處方是什麼？")
    assert result.passed is False
    assert result.modified_text == "抱歉，無法回答醫療問題。"
    assert "處方" in result.reason


def test_keyword_guardrail_passes_input():
    guard = KeywordGuardrail(blocked_patterns=["處方"])
    result = guard.check_input("今天天氣很好。")
    assert result.passed is True
    assert result.modified_text is None


def test_keyword_guardrail_case_insensitive():
    guard = KeywordGuardrail(blocked_patterns=["BadWord"], case_sensitive=False)
    result = guard.check_input("This contains BADWORD in it.")
    assert result.passed is False


def test_keyword_guardrail_blocks_output():
    guard = KeywordGuardrail(
        blocked_patterns=["機密"],
        output_replacement="（內容已過濾）",
    )
    result = guard.check_output("這是機密資訊。")
    assert result.passed is False
    assert result.modified_text == "（內容已過濾）"


def test_keyword_guardrail_output_replacement_text():
    guard = KeywordGuardrail(
        blocked_patterns=["danger"],
        output_replacement="Safe content.",
    )
    # 匹配 → 替換
    result = guard.check_output("This is a danger zone.")
    assert result.passed is False
    assert result.modified_text == "Safe content."

    # 不匹配 → 不替換
    result2 = guard.check_output("This is safe.")
    assert result2.passed is True
