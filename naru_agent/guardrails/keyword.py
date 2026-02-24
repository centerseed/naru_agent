from __future__ import annotations

import re

from naru_agent.guardrails.base import BaseGuardrail, GuardrailResult


class KeywordGuardrail(BaseGuardrail):
    """Block or rewrite messages matching keyword/regex patterns.

    Usage:
        guardrail = KeywordGuardrail(
            blocked_patterns=["處方", "劑量", r"診斷.*疾病"],
            input_message="抱歉，我無法回答醫療相關問題，建議您諮詢專業醫療人員。",
            output_replacement="建議您諮詢專業醫療人員以獲得更準確的建議。",
        )
    """

    def __init__(
        self,
        blocked_patterns: list[str],
        input_message: str = "This request cannot be processed.",
        output_replacement: str | None = None,
        case_sensitive: bool = False,
    ):
        self._patterns = [
            re.compile(p, 0 if case_sensitive else re.IGNORECASE)
            for p in blocked_patterns
        ]
        self._input_message = input_message
        self._output_replacement = output_replacement

    def check_input(self, message: str) -> GuardrailResult:
        for pattern in self._patterns:
            if pattern.search(message):
                return GuardrailResult(
                    passed=False,
                    modified_text=self._input_message,
                    reason=f"Input matched blocked pattern: {pattern.pattern}",
                )
        return GuardrailResult(passed=True)

    def check_output(self, response: str) -> GuardrailResult:
        if self._output_replacement is None:
            return GuardrailResult(passed=True)

        for pattern in self._patterns:
            if pattern.search(response):
                return GuardrailResult(
                    passed=False,
                    modified_text=self._output_replacement,
                    reason=f"Output matched blocked pattern: {pattern.pattern}",
                )
        return GuardrailResult(passed=True)
