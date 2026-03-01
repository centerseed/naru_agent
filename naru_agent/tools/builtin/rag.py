from __future__ import annotations

from typing import Any, Callable

from naru_agent.tools.base import BaseTool

# NOTE: This module is deprecated.
# Use naru_agent.knowledge.ChromaKnowledgeStore with NaruAgent instead.


class RAGTool(BaseTool):
    """Generic RAG query tool. Wraps any vector search function.

    Usage:
        rag = RAGTool(
            name="search_products",
            description="Search health product database",
            search_fn=my_chroma_search,  # (query: str, top_k: int) -> list[dict]
            top_k=3,
        )
    """

    def __init__(
        self,
        name: str,
        description: str,
        search_fn: Callable[..., list[dict[str, Any]]],
        top_k: int = 3,
        format_fn: Callable[[list[dict[str, Any]]], str] | None = None,
    ):
        self.name = name
        self.description = description
        self.args_schema = None  # uses default: query: str
        self._search_fn = search_fn
        self._top_k = top_k
        self._format_fn = format_fn or self._default_format

    def run(self, query: str = "", **kwargs: Any) -> str:
        results = self._search_fn(query=query, top_k=self._top_k, **kwargs)
        return self._format_fn(results)

    @staticmethod
    def _default_format(results: list[dict[str, Any]]) -> str:
        if not results:
            return "No relevant results found."
        parts = []
        for i, r in enumerate(results, 1):
            content = r.get("content", r.get("text", r.get("data", str(r))))
            parts.append(f"[{i}] {content}")
        return "\n\n".join(parts)
