"""Session state store — tracks entities and metadata across turns."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentSessionState:
    """Tracks entities presented in the last response for coreference resolution."""

    session_id: str
    last_presented_entities: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)


class BaseSessionStateStore(ABC):
    """Abstract base for session state storage backends."""

    @abstractmethod
    def get(self, session_id: str) -> AgentSessionState | None:
        ...

    @abstractmethod
    def save(self, session_id: str, state: AgentSessionState) -> None:
        ...

    @abstractmethod
    def clear(self, session_id: str) -> None:
        ...


class InMemorySessionStateStore(BaseSessionStateStore):
    """Simple in-memory dict implementation of BaseSessionStateStore."""

    def __init__(self) -> None:
        self._store: dict[str, AgentSessionState] = {}

    def get(self, session_id: str) -> AgentSessionState | None:
        return self._store.get(session_id)

    def save(self, session_id: str, state: AgentSessionState) -> None:
        self._store[session_id] = state

    def clear(self, session_id: str) -> None:
        self._store.pop(session_id, None)
