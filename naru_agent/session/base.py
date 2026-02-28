from __future__ import annotations

from abc import ABC, abstractmethod


class BaseSessionStore(ABC):
    """Abstract session store for persisting conversation history."""

    @abstractmethod
    async def get(self, session_id: str) -> list[dict] | None:
        """Load conversation history for a session. Returns None if not found."""
        ...

    @abstractmethod
    async def save(self, session_id: str, history: list[dict]) -> None:
        """Save conversation history for a session."""
        ...

    @abstractmethod
    async def delete(self, session_id: str) -> None:
        """Delete a session's history."""
        ...
