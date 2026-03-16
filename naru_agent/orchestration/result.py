"""OrchestrationResult — extends NaruResult with orchestration-specific fields."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from naru_agent.agent import NaruResult

if TYPE_CHECKING:
    from naru_agent.orchestration.intent import OrchestratorIntent
    from naru_agent.orchestration.trace import AgentDecisionTrace


@dataclass
class PendingConfirmation:
    """Represents a pending confirmation awaiting user response."""

    type: str  # noqa: A003
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrchestrationResult(NaruResult):
    """Extends NaruResult with orchestration-specific fields.

    ``decision_trace`` is typed as ``| None`` due to dataclass inheritance
    constraints (parent has defaults → children must too), but it is
    **always set** by ``AgentOrchestrator._wrap_result()`` and will never
    be ``None`` at runtime.
    """

    decision_trace: AgentDecisionTrace | None = None  # type: ignore[assignment]  # always set at runtime
    pending_confirmation: PendingConfirmation | None = None
    orchestration_intent: OrchestratorIntent | None = None  # type: ignore[type-arg]
