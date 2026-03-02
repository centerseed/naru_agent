from __future__ import annotations

import asyncio
import copy

from naru_agent.compression.base import BaseSummaryStore, CompressedSummary


class InMemorySummaryStore(BaseSummaryStore):
    """In-memory summary store. Suitable for single-process deployments."""

    def __init__(self) -> None:
        self._store: dict[str, CompressedSummary] = {}
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        """Lazy-init the lock inside the running event loop."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def get(self, session_id: str) -> CompressedSummary | None:
        async with self._get_lock():
            data = self._store.get(session_id)
            return copy.copy(data) if data is not None else None

    async def save(self, session_id: str, summary: CompressedSummary) -> None:
        async with self._get_lock():
            self._store[session_id] = copy.copy(summary)

    async def delete(self, session_id: str) -> None:
        async with self._get_lock():
            self._store.pop(session_id, None)
