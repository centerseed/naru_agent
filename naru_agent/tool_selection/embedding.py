from __future__ import annotations

import hashlib
import json
import logging
import threading
from typing import Any, Callable

from naru_agent.tools.base import BaseTool

from .base import BaseToolSelector, ToolSelectionResult

logger = logging.getLogger(__name__)


def _tool_to_text(tool: BaseTool) -> str:
    """Convert a tool into a text representation for embedding."""
    parts = [tool.name, tool.description]
    if tool.args_schema:
        schema = tool.args_schema.model_json_schema()
        for prop_name, prop_info in schema.get("properties", {}).items():
            prop_type = prop_info.get("type", "")
            prop_desc = prop_info.get("description", "")
            parts.append(f"{prop_name} ({prop_type}): {prop_desc}")
    return " | ".join(parts)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _tools_cache_key(tools: list[BaseTool]) -> str:
    """Build a cache key from tool names + descriptions + schema, so changes invalidate cache."""
    h = hashlib.md5(usedforsecurity=False)
    for t in sorted(tools, key=lambda t: t.name):
        h.update(t.name.encode())
        h.update(t.description.encode())
        if t.args_schema:
            h.update(json.dumps(t.args_schema.model_json_schema(), sort_keys=True).encode())
    return h.hexdigest()


def litellm_embed_fn(model: str = "gemini/text-embedding-004") -> Callable[[list[str]], list[list[float]]]:
    """Create an embed_fn using LiteLLM (works with Gemini, OpenAI, etc.).

    Usage:
        selector = EmbeddingToolSelector(embed_fn=litellm_embed_fn())
        selector = EmbeddingToolSelector(embed_fn=litellm_embed_fn("text-embedding-3-small"))
    """
    import litellm as _litellm

    def _embed(texts: list[str]) -> list[list[float]]:
        resp = _litellm.embedding(model=model, input=texts)
        return [d["embedding"] for d in resp.data]

    return _embed


class EmbeddingToolSelector(BaseToolSelector):
    """Select tools by embedding similarity between query and tool descriptions."""

    def __init__(
        self,
        *,
        top_k: int = 5,
        similarity_threshold: float = 0.0,
        min_tools_to_filter: int = 10,
        embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
        model_name: str = "all-MiniLM-L6-v2",
    ):
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold
        self.min_tools_to_filter = min_tools_to_filter
        self._embed_fn = embed_fn
        self._model_name = model_name

        self._model: Any = None
        self._model_lock = threading.Lock()

        self._cache: dict[str, dict[str, list[float]]] = {}
        self._cache_lock = threading.Lock()

    def _get_embed_fn(self) -> Callable[[list[str]], list[list[float]]]:
        if self._embed_fn is not None:
            return self._embed_fn

        with self._model_lock:
            if self._model is None:
                try:
                    from sentence_transformers import SentenceTransformer
                except ImportError as e:
                    raise ImportError(
                        "sentence-transformers is required for EmbeddingToolSelector. "
                        "Install it with: pip install naru_agent[embeddings]"
                    ) from e
                self._model = SentenceTransformer(self._model_name)
            model = self._model

        def _encode(texts: list[str]) -> list[list[float]]:
            embeddings = model.encode(texts, convert_to_numpy=True)
            return [e.tolist() for e in embeddings]

        return _encode

    def _ensure_tool_embeddings(
        self, tools: list[BaseTool]
    ) -> dict[str, list[float]]:
        cache_key = _tools_cache_key(tools)

        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

            # Compute inside lock to avoid duplicate work across threads (#4 TOCTOU)
            embed_fn = self._get_embed_fn()
            texts = [_tool_to_text(t) for t in tools]
            embeddings = embed_fn(texts)

            result = {t.name: emb for t, emb in zip(tools, embeddings)}
            self._cache[cache_key] = result
            return result

    def invalidate_cache(self) -> None:
        with self._cache_lock:
            self._cache.clear()

    def select_tools(
        self,
        tools: list[BaseTool],
        query: str,
        context: list[dict] | None = None,
        used_tool_names: set[str] | None = None,
    ) -> ToolSelectionResult:
        used_tool_names = used_tool_names or set()

        if len(tools) <= self.min_tools_to_filter:
            return ToolSelectionResult(
                selected_tools=list(tools),
                all_tools=list(tools),
                scores={t.name: 1.0 for t in tools},
            )

        tool_embeddings = self._ensure_tool_embeddings(tools)
        embed_fn = self._get_embed_fn()
        query_embedding = embed_fn([query])[0]

        scores: dict[str, float] = {}
        for t in tools:
            scores[t.name] = _cosine_similarity(query_embedding, tool_embeddings[t.name])

        sorted_tools = sorted(tools, key=lambda t: scores[t.name], reverse=True)

        selected: list[BaseTool] = []
        selected_names: set[str] = set()

        # Always include used tools first, sorted by score, capped to avoid exceeding budget
        max_used = max(self.top_k // 2, 1)
        used_tools = [t for t in tools if t.name in used_tool_names]
        used_tools.sort(key=lambda t: scores[t.name], reverse=True)
        for t in used_tools[:max_used]:
            selected.append(t)
            selected_names.add(t.name)

        # Fill remaining slots with top-k by score (that pass threshold)
        for t in sorted_tools:
            if len(selected) >= self.top_k:
                break
            if t.name not in selected_names and scores[t.name] >= self.similarity_threshold:
                selected.append(t)
                selected_names.add(t.name)

        return ToolSelectionResult(
            selected_tools=selected,
            all_tools=list(tools),
            scores=scores,
        )
