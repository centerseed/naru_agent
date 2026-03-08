"""Hybrid knowledge store that merges results from multiple stores."""

from __future__ import annotations

from naru_agent.knowledge.base import BaseKnowledgeStore, KnowledgeResult


class HybridKnowledgeStore(BaseKnowledgeStore):
    """Merge search results from multiple knowledge stores with weighted scoring.

    Args:
        stores: List of knowledge stores to query.
        weights: Per-store weight multipliers (default: equal weights).
    """

    def __init__(
        self,
        stores: list[BaseKnowledgeStore],
        weights: list[float] | None = None,
    ) -> None:
        if not stores:
            raise ValueError("At least one store is required")
        if weights and len(weights) != len(stores):
            raise ValueError("weights must match the number of stores")
        self._stores = stores
        self._weights = weights or [1.0] * len(stores)

    def search(self, query: str, top_k: int = 3) -> list[KnowledgeResult]:
        """Search all stores and return merged, re-scored results."""
        all_results: list[KnowledgeResult] = []

        for store, weight in zip(self._stores, self._weights):
            # Request more results per store for better diversity after merging
            per_store_k = top_k * len(self._stores)
            results = store.search(query, top_k=per_store_k)
            for r in results:
                all_results.append(
                    KnowledgeResult(
                        text=r.text,
                        score=r.score * weight,
                        metadata=r.metadata,
                    )
                )

        all_results.sort(key=lambda r: r.score, reverse=True)
        return all_results[:top_k]
