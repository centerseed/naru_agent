"""Base abstractions for intent classification."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class IntentResult:
    """Result of intent classification.

    Attributes:
        needs_knowledge: Whether the query requires RAG knowledge context.
        needs_tools: Whether the query requires tool calls.
        raw: The raw classifier response string (e.g. "YY", "NN").
    """

    needs_knowledge: bool = True
    needs_tools: bool = True
    raw: str = ""


class BaseIntentClassifier(ABC):
    """Abstract interface for intent classification."""

    @abstractmethod
    def classify(self, message: str) -> IntentResult:
        """Classify a user message and return an IntentResult."""
        ...
