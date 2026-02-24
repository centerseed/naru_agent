from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel, Field


class MemoryItem(BaseModel):
    id: str
    user_id: str
    content: str
    metadata: dict = Field(default_factory=dict)
    score: float | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MemoryStore(ABC):
    """Abstract vector store interface for memory persistence."""

    @abstractmethod
    def add(self, item: MemoryItem, embedding: list[float]) -> None:
        ...

    @abstractmethod
    def search(
        self, user_id: str, embedding: list[float], top_k: int = 5
    ) -> list[MemoryItem]:
        ...

    @abstractmethod
    def update(self, item_id: str, content: str, embedding: list[float]) -> None:
        ...

    @abstractmethod
    def delete(self, item_id: str) -> None:
        ...

    @abstractmethod
    def get_all(self, user_id: str) -> list[MemoryItem]:
        ...
