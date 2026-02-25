"""Mem0 adapter — wraps mem0 OSS or Platform as a drop-in memory manager.

Usage:
    from mem0 import Memory
    from naru_agent.memory import Mem0MemoryManager

    m = Memory.from_config({...})
    manager = Mem0MemoryManager(client=m)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from mem0 import Memory  # noqa: F401 — validated at import time

from naru_agent.memory.base import MemoryItem

logger = logging.getLogger(__name__)


class Mem0MemoryManager:
    """Memory manager backed by mem0 (OSS or Platform).

    Accepts a ``mem0.Memory`` or ``mem0.MemoryClient`` instance.
    The caller is responsible for configuring the client (LLM, vector store, etc.).
    """

    def __init__(self, client: object) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Public API (mirrors MemoryManager)
    # ------------------------------------------------------------------

    def add(
        self,
        user_id: str,
        messages: list[dict[str, str]],
        infer: bool = True,
        memory_type: str | None = None,
        agent_id: str | None = None,
        **kwargs,
    ) -> list[dict]:
        """Extract and store memories from *messages* via mem0.

        Args:
            infer: True（預設）→ 語義記憶，LLM 萃取事實。
                   False → 短期記憶，直接存原始對話。
            memory_type: "procedural_memory" → 程序記憶（需搭配 agent_id）。
            agent_id: 程序記憶專用的 agent 識別碼。
        """
        call_kwargs: dict = {"user_id": user_id, "infer": infer}
        if memory_type is not None:
            call_kwargs["memory_type"] = memory_type
        if agent_id is not None:
            call_kwargs["agent_id"] = agent_id
        call_kwargs.update(kwargs)

        result = self._client.add(messages, **call_kwargs)
        return self._normalise_add_result(result)

    def search(
        self,
        user_id: str,
        query: str,
        top_k: int = 5,
        agent_id: str | None = None,
    ) -> list[MemoryItem]:
        """Semantic search over stored memories."""
        call_kwargs: dict = {"user_id": user_id, "limit": top_k}
        if agent_id is not None:
            call_kwargs["agent_id"] = agent_id
        result = self._client.search(query, **call_kwargs)
        return self._to_memory_items(result, user_id)

    def get_context_string(
        self,
        user_id: str,
        query: str,
        top_k: int = 5,
        agent_id: str | None = None,
    ) -> str:
        """Return a pre-formatted context string for prompt injection."""
        memories = self.search(user_id, query, top_k, agent_id=agent_id)
        if not memories:
            return ""
        return "\n".join(f"- {m.content}" for m in memories)

    def get_all(self, user_id: str, agent_id: str | None = None) -> list[MemoryItem]:
        """Return every memory for *user_id*."""
        call_kwargs: dict = {"user_id": user_id}
        if agent_id is not None:
            call_kwargs["agent_id"] = agent_id
        result = self._client.get_all(**call_kwargs)
        return self._to_memory_items(result, user_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_add_result(result: object) -> list[dict]:
        """Normalise mem0 add() return into ``[{"event": ..., "memory": ...}]``."""
        # mem0 OSS returns {"results": [{"event": "ADD", "memory": "..."}]}
        # mem0 Platform returns [{"event": "ADD", "memory": "..."}]
        if isinstance(result, dict):
            return result.get("results", [])
        if isinstance(result, list):
            return result
        return []

    @staticmethod
    def _to_memory_items(result: object, user_id: str) -> list[MemoryItem]:
        """Convert mem0 search/get_all results into ``MemoryItem`` list."""
        # mem0 OSS returns {"results": [{"id": ..., "memory": ...}]}
        # mem0 Platform returns [{"id": ..., "memory": ...}]
        if isinstance(result, dict):
            entries = result.get("results", [])
        elif isinstance(result, list):
            entries = result
        else:
            return []

        items: list[MemoryItem] = []
        for entry in entries:
            items.append(
                MemoryItem(
                    id=entry.get("id", str(uuid.uuid4())),
                    user_id=entry.get("user_id", user_id),
                    content=entry.get("memory", ""),
                    metadata=entry.get("metadata") or {},
                    score=entry.get("score"),
                    created_at=_parse_dt(entry.get("created_at")),
                    updated_at=_parse_dt(entry.get("updated_at")),
                )
            )
        return items


def _parse_dt(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.utcnow()
