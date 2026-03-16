"""@ac14 — OrchestrationResult backward compatibility with NaruResult."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from naru_agent.agent import NaruResult
from naru_agent.orchestration.result import OrchestrationResult, PendingConfirmation
from naru_agent.orchestration.trace import AgentDecisionTrace, OrchestrationTimings


def _make_trace() -> AgentDecisionTrace:
    return AgentDecisionTrace(
        trace_id="t-1",
        phase_reached="delegate",
        intent_resolved=None,
        timings=OrchestrationTimings(total=0.01),
    )


class TestOrchestrationResult:
    """@ac14 — OrchestrationResult extends NaruResult."""

    def test_is_naru_result_subclass(self):
        result = OrchestrationResult(content="hi")
        assert isinstance(result, NaruResult)

    def test_inherits_naru_result_fields(self):
        result = OrchestrationResult(
            content="test",
            blocked=False,
            usage={"total_tokens": 5},
            session_id="sess-1",
        )
        assert result.content == "test"
        assert result.blocked is False
        assert result.usage == {"total_tokens": 5}
        assert result.session_id == "sess-1"

    def test_extra_fields_default_to_none(self):
        result = OrchestrationResult(content="hi")
        assert result.decision_trace is None
        assert result.pending_confirmation is None
        assert result.orchestration_intent is None

    def test_can_attach_decision_trace(self):
        trace = _make_trace()
        result = OrchestrationResult(content="hi", decision_trace=trace)
        assert result.decision_trace is trace
        assert result.decision_trace.trace_id == "t-1"

    def test_pending_confirmation_dataclass(self):
        pc = PendingConfirmation(type="delete", payload={"id": 42})
        assert pc.type == "delete"
        assert pc.payload["id"] == 42

    def test_naru_result_consumer_accepts_orchestration_result(self):
        """Functions that accept NaruResult should accept OrchestrationResult."""

        def consume(r: NaruResult) -> str:
            return r.content

        result = OrchestrationResult(content="compat")
        assert consume(result) == "compat"
