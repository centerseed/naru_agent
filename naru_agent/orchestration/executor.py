"""BaseDirectExecutor — handles intents without calling the delegate LLM agent."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    from naru_agent.orchestration.intent import OrchestratorIntent
    from naru_agent.orchestration.result import OrchestrationResult

T = TypeVar("T", bound=str)


class BaseDirectExecutor(ABC, Generic[T]):
    """Handles intents without calling the delegate LLM agent.

    Return ``None`` from ``execute()`` to fallthrough to the next executor
    or the delegate.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name for this executor (used in trace)."""
        ...

    @abstractmethod
    def can_handle(self, intent: OrchestratorIntent[T]) -> bool:
        """Return True if this executor can handle the given intent."""
        ...

    @abstractmethod
    def execute(
        self,
        *,
        message: str,
        intent: OrchestratorIntent[T],
        options: dict | None = None,
    ) -> OrchestrationResult | None:
        """Execute and return a result, or ``None`` to fallthrough."""
        ...
