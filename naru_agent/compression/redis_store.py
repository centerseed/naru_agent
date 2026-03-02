from __future__ import annotations

import json
import logging
from typing import Any

from naru_agent.compression.base import BaseSummaryStore, CompressedSummary

logger = logging.getLogger(__name__)


class RedisSummaryStore(BaseSummaryStore):
    """Redis-backed summary store for multi-instance deployments.

    Requires redis[asyncio]>=5.0:
        pip install "naru_agent[redis]"
    """

    def __init__(
        self,
        client: Any,
        ttl: int | None = None,
        prefix: str = "naru:summary:",
    ) -> None:
        self._client = client
        self._ttl = ttl
        self._prefix = prefix

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    async def get(self, session_id: str) -> CompressedSummary | None:
        data = await self._client.get(self._key(session_id))
        if data is None:
            return None
        try:
            d = json.loads(data)
            return CompressedSummary(**d)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.error(
                "Corrupted summary data for '%s', discarding: %s", session_id, e,
            )
            return None

    async def save(self, session_id: str, summary: CompressedSummary) -> None:
        key = self._key(session_id)
        from dataclasses import asdict
        value = json.dumps(asdict(summary), ensure_ascii=False)
        if self._ttl is not None:
            await self._client.setex(key, self._ttl, value)
        else:
            await self._client.set(key, value)

    async def delete(self, session_id: str) -> None:
        await self._client.delete(self._key(session_id))
