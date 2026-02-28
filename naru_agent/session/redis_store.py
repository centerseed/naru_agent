from __future__ import annotations

import json
import logging
from typing import Any

from naru_agent.session.base import BaseSessionStore

logger = logging.getLogger(__name__)


class RedisSessionStore(BaseSessionStore):
    """Redis-backed session store for multi-instance deployments.

    Requires redis[asyncio]>=5.0:
        pip install "naru_agent[redis]"

    Usage:
        import redis.asyncio as aioredis
        client = aioredis.from_url("redis://localhost")
        store = RedisSessionStore(client, ttl=3600)
    """

    def __init__(self, client: Any, ttl: int | None = None, prefix: str = "naru:session:") -> None:
        self._client = client
        self._ttl = ttl
        self._prefix = prefix

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    async def get(self, session_id: str) -> list[dict] | None:
        data = await self._client.get(self._key(session_id))
        if data is None:
            return None
        try:
            return json.loads(data)
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(
                "Corrupted session data for '%s', discarding: %s", session_id, e,
            )
            return None

    async def save(self, session_id: str, history: list[dict]) -> None:
        key = self._key(session_id)
        value = json.dumps(history, ensure_ascii=False)
        if self._ttl is not None:
            await self._client.setex(key, self._ttl, value)
        else:
            await self._client.set(key, value)

    async def delete(self, session_id: str) -> None:
        await self._client.delete(self._key(session_id))
