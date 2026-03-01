"""LLM-based intent classifier using litellm for fast classification."""

from __future__ import annotations

import logging
from typing import Any

from naru_agent.intent.base import BaseIntentClassifier, IntentResult

logger = logging.getLogger(__name__)


class LLMIntentClassifier(BaseIntentClassifier):
    """Fast LLM-based intent classifier.

    Uses a lightweight model to classify whether a message needs
    knowledge context and/or tool calls. Returns a 2-char code:
    "YY" / "YN" / "NY" / "NN".

    Args:
        model: LiteLLM model identifier (e.g. "gemini/gemini-2.5-flash-lite").
        api_key: Optional API key for the model.
        examples: Domain-specific few-shot examples as (message, code) tuples.
        max_tokens: Max tokens for the classification response.
    """

    def __init__(
        self,
        model: str = "gemini/gemini-2.5-flash-lite",
        api_key: str | None = None,
        examples: list[tuple[str, str]] | None = None,
        max_tokens: int = 30,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._max_tokens = max_tokens
        self._examples = examples or [
            ("你好", "NN"),
            ("謝謝", "NN"),
            ("什麼是乳酸閾值", "YN"),
            ("今天練什麼", "NY"),
            ("全馬跑爆了", "YY"),
            ("膝蓋痛怎麼辦", "YY"),
        ]

    def classify(self, message: str) -> IntentResult:
        """Classify a user message via a fast LLM call."""
        import litellm

        prompt = self._build_prompt(message)
        try:
            kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": self._max_tokens,
                "temperature": 0,
            }
            if self._api_key:
                kwargs["api_key"] = self._api_key

            resp = litellm.completion(**kwargs)
            raw = resp.choices[0].message.content.strip()
            return self._parse_response(raw)
        except Exception:
            logger.warning("Intent classification failed, defaulting to YY")
            return IntentResult(needs_knowledge=True, needs_tools=True, raw="YY")

    def _build_prompt(self, message: str) -> str:
        lines = [
            "判斷用戶訊息需要什麼。回答兩個字母，"
            "第一個=是否需要專業知識，第二個=是否需要查用戶資料。",
            "Y=需要 N=不需要",
            "",
            "範例：",
        ]
        for msg, code in self._examples:
            lines.append(f"「{msg}」→ {code}")
        lines.append("")
        lines.append(f"「{message}」→")
        return "\n".join(lines)

    @staticmethod
    def _parse_response(raw: str) -> IntentResult:
        """Parse "YY" -> IntentResult(needs_knowledge=True, needs_tools=True).

        Uses regex to find a valid 2-char code anywhere in the response,
        handling cases like "Answer: YY" or "```YN```".
        Defaults to True for malformed responses.
        """
        import re

        cleaned = raw.strip().upper()
        match = re.search(r"\b[YN]{2}\b", cleaned)
        if match:
            code = match.group()
            return IntentResult(
                needs_knowledge=code[0] == "Y",
                needs_tools=code[1] == "Y",
                raw=code,
            )
        # Malformed — default to True for safety
        return IntentResult(
            needs_knowledge=True,
            needs_tools=True,
            raw=cleaned,
        )
