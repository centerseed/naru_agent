"""Intent types and resolvers for the orchestration layer."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

logger = logging.getLogger(__name__)

GenericIntentObject = str  # "greeting" | "query" | "action" | "confirmation" | "unknown"

T = TypeVar("T", bound=str)


@dataclass
class OrchestratorIntent(Generic[T]):
    """Resolved intent from an intent resolver."""

    object: T  # noqa: A003
    confidence: float
    requires_confirmation: bool = False


@dataclass
class IntentResolveInput:
    """Input to an intent resolver."""

    message: str
    history: list[Any] = field(default_factory=list)
    session_state: Any = None


class BaseIntentResolver(ABC, Generic[T]):
    """Abstract base for intent resolvers."""

    @abstractmethod
    def resolve(self, input: IntentResolveInput) -> OrchestratorIntent[T]:  # noqa: A002
        ...


@dataclass
class DeterministicPattern(Generic[T]):
    """A regex pattern mapped to a fixed intent."""

    pattern: Any  # re.Pattern[str]
    intent: OrchestratorIntent[T]


class DeterministicIntentResolver(BaseIntentResolver[T]):
    """Fast pattern matching, no LLM calls.

    Returns the first matching pattern's intent, or an 'unknown' intent with
    confidence 0 when no pattern matches.
    """

    def __init__(self, patterns: list[DeterministicPattern[T]]) -> None:
        self._patterns = patterns

    def resolve(self, input: IntentResolveInput) -> OrchestratorIntent[T]:  # noqa: A002
        for entry in self._patterns:
            if entry.pattern.search(input.message):
                return entry.intent
        return OrchestratorIntent(object="unknown", confidence=0.0)  # type: ignore[arg-type]


class LLMFallbackIntentResolver(BaseIntentResolver[T]):
    """Tries deterministic first, falls back to an LLM classifier.

    The fallback_agent only needs a ``chat(message: str)`` method that returns
    an object with a ``content`` attribute (str).  NaruAgent satisfies this.
    """

    def __init__(
        self,
        primary: BaseIntentResolver[T],
        fallback_agent: Any,
        parse_response: Any = None,
    ) -> None:
        self._primary = primary
        self._fallback_agent = fallback_agent
        self._parse_response = parse_response

    def resolve(self, input: IntentResolveInput) -> OrchestratorIntent[T]:  # noqa: A002
        primary_result = self._primary.resolve(input)

        if primary_result.object != "unknown":
            return primary_result

        # Fallback to LLM
        llm_response = self._fallback_agent.chat(
            f'Classify the intent of this message: "{input.message}". '
            'Return a JSON object with "object" (string) and "confidence" (number 0-1).'
        )

        if self._parse_response is not None:
            return self._parse_response(llm_response.content)

        # Default parsing
        try:
            parsed = json.loads(llm_response.content)
            return OrchestratorIntent(
                object=parsed.get("object", "unknown"),
                confidence=float(parsed.get("confidence", 0.5)),
            )
        except Exception:  # noqa: BLE001
            return OrchestratorIntent(object="unknown", confidence=0.0)  # type: ignore[arg-type]
