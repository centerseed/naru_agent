"""Orchestration Integration Tests — shared scenarios from tests/shared/scenarios/orchestration.json.

Mirrors js/tests/integration/test_orchestration.test.ts.

Covers:
    @ac11 — 單一 Agent Passthrough
    @ac12 — Intent 路由
    @ac13 — Direct Executor 繞過 LLM
    @ac14 — 多步驟確認流程

Uses mock delegates (not real LLM) to test routing logic.

Execute:
    pytest tests/integration/test_orchestration.py -v --tb=short
"""

from __future__ import annotations

import re

import pytest

from naru_agent.agent import NaruResult
from naru_agent.orchestration import (
    AgentOrchestrator,
    AgentOrchestratorConfig,
    BaseDirectExecutor,
    DeterministicIntentResolver,
    DeterministicPattern,
    InMemoryPendingStateManager,
    OrchestrationResult,
    OrchestratorIntent,
    PendingState,
)
from tests.shared.scenario_runner import assert_scenario_result, load_scenarios


# ---------------------------------------------------------------------------
# Load shared scenarios
# ---------------------------------------------------------------------------

_scenarios_file = load_scenarios("orchestration.json")
_scenarios = {s["id"]: s for s in _scenarios_file["scenarios"]}


# ---------------------------------------------------------------------------
# Mock delegate factory (mirrors JS mockDelegate)
# ---------------------------------------------------------------------------


def _mock_delegate(name: str, response: str = "mock response"):
    """Create a mock AgentChatDelegate returning a fixed response."""

    class _Delegate:
        def chat(
            self,
            message: str,
            user_id: str | None = None,
            session_id: str | None = None,
        ) -> NaruResult:
            return NaruResult(
                content=f"[{name}] {response}",
                blocked=False,
                usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            )

    return _Delegate()


# ---------------------------------------------------------------------------
# @ac11 — 單一 Agent Passthrough
# ---------------------------------------------------------------------------


class TestPassthrough:
    """@ac11 — 單一 Agent Passthrough."""

    def test_single_agent_passthrough_returns_delegate_response(self):
        scenario = _scenarios["single_agent_passthrough"]
        delegate = _mock_delegate("default")
        orchestrator = AgentOrchestrator(AgentOrchestratorConfig(delegate=delegate))

        result = orchestrator.chat(scenario["input"])

        assert_scenario_result(result, scenario["expect"])
        assert isinstance(result, OrchestrationResult)
        assert result.decision_trace is not None
        assert result.decision_trace.phase_reached == "delegate"

    def test_passes_through_options_to_delegate(self):
        received = {}

        class _Delegate:
            def chat(self, message, user_id=None, session_id=None):
                received["user_id"] = user_id
                received["session_id"] = session_id
                return NaruResult(content="ok", blocked=False)

        orchestrator = AgentOrchestrator(AgentOrchestratorConfig(delegate=_Delegate()))
        orchestrator.chat("test", user_id="u1", session_id="s1")

        assert received["user_id"] == "u1"
        assert received["session_id"] == "s1"


# ---------------------------------------------------------------------------
# @ac12 — Intent 路由
# ---------------------------------------------------------------------------


def _build_order_orchestrator():
    """Build an orchestrator with order/product intent routing."""
    default_delegate = _mock_delegate("default", "default response")
    order_delegate = _mock_delegate("order_agent", "order response")
    product_delegate = _mock_delegate("product_agent", "product response")

    intent_resolver = DeterministicIntentResolver(
        [
            DeterministicPattern(
                pattern=re.compile(r"訂單"),
                intent=OrchestratorIntent(object="order", confidence=1.0),
            ),
            DeterministicPattern(
                pattern=re.compile(r"產品|搜尋"),
                intent=OrchestratorIntent(object="product", confidence=1.0),
            ),
        ]
    )

    delegates = {
        "order": order_delegate,
        "product": product_delegate,
    }

    return AgentOrchestrator(
        AgentOrchestratorConfig(
            delegate=default_delegate,
            delegates=delegates,
            intent_resolver=intent_resolver,
        )
    )


class TestIntentRouting:
    """@ac12 — Intent 路由."""

    def test_routes_order_query_to_order_delegate(self):
        scenario = _scenarios["intent_routing_order"]
        orchestrator = _build_order_orchestrator()

        result = orchestrator.chat(scenario["input"])

        assert_scenario_result(result, scenario["expect"])
        assert "order_agent" in result.content

    def test_routes_product_query_to_product_delegate(self):
        scenario = _scenarios["intent_routing_product"]
        orchestrator = _build_order_orchestrator()

        result = orchestrator.chat(scenario["input"])

        assert_scenario_result(result, scenario["expect"])
        assert "product_agent" in result.content

    def test_uses_default_delegate_when_no_pattern_matches(self):
        scenario = _scenarios["intent_routing_default"]
        orchestrator = _build_order_orchestrator()

        result = orchestrator.chat(scenario["input"])

        assert_scenario_result(result, scenario["expect"])
        assert "default" in result.content

    def test_decision_trace_records_delegate_used(self):
        orchestrator = _build_order_orchestrator()

        result = orchestrator.chat("查詢訂單狀態")

        assert result.decision_trace is not None
        assert result.decision_trace.delegate_used == "order"


# ---------------------------------------------------------------------------
# @ac13 — Direct Executor
# ---------------------------------------------------------------------------


class _PingExecutor(BaseDirectExecutor):
    """Direct executor that responds 'pong' to 'ping' intent."""

    @property
    def name(self) -> str:
        return "ping-executor"

    def can_handle(self, intent: OrchestratorIntent) -> bool:
        return intent.object == "ping"

    def execute(self, *, message, intent, options=None) -> NaruResult | None:
        return NaruResult(
            content="pong",
            blocked=False,
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )


class TestDirectExecutor:
    """@ac13 — Direct Executor 繞過 LLM."""

    def test_direct_executor_handles_ping_without_llm(self):
        scenario = _scenarios["direct_executor"]
        delegate = _mock_delegate("default", "should not be called")

        intent_resolver = DeterministicIntentResolver(
            [
                DeterministicPattern(
                    pattern=re.compile(r"^ping$"),
                    intent=OrchestratorIntent(object="ping", confidence=1.0),
                ),
            ]
        )

        orchestrator = AgentOrchestrator(
            AgentOrchestratorConfig(
                delegate=delegate,
                intent_resolver=intent_resolver,
                direct_executors=[_PingExecutor()],
            )
        )

        result = orchestrator.chat(scenario["input"])

        assert_scenario_result(result, scenario["expect"])
        assert result.decision_trace.phase_reached == "direct_execution"
        assert result.decision_trace.direct_executor_used == "ping-executor"

    def test_falls_through_to_delegate_when_executor_returns_none(self):
        delegate = _mock_delegate("default", "fallthrough response")

        class _NullExecutor(BaseDirectExecutor):
            @property
            def name(self):
                return "null-executor"

            def can_handle(self, intent):
                return True

            def execute(self, *, message, intent, options=None):
                return None

        orchestrator = AgentOrchestrator(
            AgentOrchestratorConfig(
                delegate=delegate,
                direct_executors=[_NullExecutor()],
            )
        )

        result = orchestrator.chat("anything")

        assert "default" in result.content


# ---------------------------------------------------------------------------
# @ac14 — 多步驟確認流程
# ---------------------------------------------------------------------------


class TestMultiStepConfirmation:
    """@ac14 — 多步驟確認流程."""

    def test_pending_state_stores_confirmation_request(self):
        scenario = _scenarios["multi_step_confirmation"]
        pending_manager = InMemoryPendingStateManager()
        session_id = "confirm-test-session"

        pending_manager.set_pending(
            session_id,
            PendingState(type="delete_orders", payload={"all": True}),
        )

        delegate = _mock_delegate("default", "executed deletion")
        orchestrator = AgentOrchestrator(
            AgentOrchestratorConfig(
                delegate=delegate,
                pending_state_manager=pending_manager,
            )
        )

        confirmation_input = scenario.get("confirmation_input", "確認")
        result = orchestrator.chat(confirmation_input, session_id=session_id)

        assert_scenario_result(result, scenario["expect"])
        assert "delete_orders" in result.content
        assert result.decision_trace.phase_reached == "pending_confirmation"

    def test_rejection_clears_pending_state(self):
        pending_manager = InMemoryPendingStateManager()
        session_id = "reject-test-session"

        pending_manager.set_pending(
            session_id,
            PendingState(type="delete_orders", payload={}),
        )

        delegate = _mock_delegate("default")
        orchestrator = AgentOrchestrator(
            AgentOrchestratorConfig(
                delegate=delegate,
                pending_state_manager=pending_manager,
            )
        )

        result = orchestrator.chat("取消", session_id=session_id)

        assert not result.blocked
        assert pending_manager.get_pending(session_id) is None

    def test_override_clears_pending_and_continues_normal_flow(self):
        pending_manager = InMemoryPendingStateManager()
        session_id = "override-test-session"

        pending_manager.set_pending(
            session_id,
            PendingState(type="delete_orders", payload={}),
        )

        delegate = _mock_delegate("default", "normal response")
        orchestrator = AgentOrchestrator(
            AgentOrchestratorConfig(
                delegate=delegate,
                pending_state_manager=pending_manager,
            )
        )

        result = orchestrator.chat("完全不同的問題", session_id=session_id)

        assert not result.blocked
        assert pending_manager.get_pending(session_id) is None
