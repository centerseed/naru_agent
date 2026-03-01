"""Base abstractions for knowledge stores (RAG)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class KnowledgeResult:
    """A single search result from a knowledge store."""

    text: str
    score: float = 0.0
    metadata: dict = field(default_factory=dict)


class BaseKnowledgeStore(ABC):
    """Abstract interface for knowledge retrieval."""

    @abstractmethod
    def search(self, query: str, top_k: int = 3) -> list[KnowledgeResult]:
        """Search the knowledge store and return ranked results."""
        ...

    def format_context(
        self,
        results: list[KnowledgeResult],
        min_score: float = 0.3,
    ) -> str:
        """Filter low-score results and join into a single context string."""
        filtered = [r for r in results if r.score >= min_score]
        if not filtered:
            return ""
        return "\n\n".join(r.text for r in filtered)
