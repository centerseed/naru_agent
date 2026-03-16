"""AgentDecisionTrace — records the decision path and timings for each orchestrator invocation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from naru_agent.orchestration.intent import OrchestratorIntent

OrchestrationPhase = Literal[
    "pending_confirmation",
    "direct_execution",
    "delegate",
    "blocked",
]


@dataclass
class OrchestrationTimings:
    """Timings (in seconds, using time.monotonic()) for each phase."""

    total: float = 0.0
    intent_resolution: float | None = None
    direct_execution: float | None = None
    delegate: float | None = None


@dataclass
class AgentDecisionTrace:
    """Records the full decision path for a single orchestrator invocation."""

    trace_id: str
    phase_reached: OrchestrationPhase
    intent_resolved: OrchestratorIntent | None  # type: ignore[type-arg]
    timings: OrchestrationTimings = field(default_factory=OrchestrationTimings)
    direct_executor_used: str | None = None
    delegate_used: str | None = None
