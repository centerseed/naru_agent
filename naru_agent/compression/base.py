from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class CompressedSummary:
    """A compressed summary of conversation history."""

    summary_text: str  # <=1K tokens summary
    compressed_through_run: int  # exclusive: runs[0:N] compressed
    created_at: float = field(default_factory=time.time)
    model_used: str = ""


class BaseSummaryStore(ABC):
    """Abstract store for persisting conversation summaries."""

    @abstractmethod
    async def get(self, session_id: str) -> CompressedSummary | None:
        """Load the latest summary for a session."""
        ...

    @abstractmethod
    async def save(self, session_id: str, summary: CompressedSummary) -> None:
        """Save a summary for a session."""
        ...

    @abstractmethod
    async def delete(self, session_id: str) -> None:
        """Delete a session's summary."""
        ...
