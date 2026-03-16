"""AgentOrchestrator — 4-phase routing + multi-agent orchestration."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Protocol, TypeVar

from naru_agent.agent import NaruResult
from naru_agent.orchestration.channel import ChannelAdapter, ChannelMessage
from naru_agent.orchestration.executor import BaseDirectExecutor
from naru_agent.orchestration.intent import (
    BaseIntentResolver,
    IntentResolveInput,
    OrchestratorIntent,
)
from naru_agent.orchestration.pending import (
    BasePendingStateManager,
    PendingState,
    classify_confirmation_disposition,
)
from naru_agent.orchestration.result import OrchestrationResult, PendingConfirmation
from naru_agent.orchestration.session_state import AgentSessionState, BaseSessionStateStore
from naru_agent.orchestration.trace import AgentDecisionTrace, OrchestrationPhase, OrchestrationTimings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=str)


class AgentChatDelegate(Protocol):
    """Any object with a chat() method.

    NaruAgent satisfies this structurally (duck typing / PEP 544).
    """

    def chat(
        self,
        message: str,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> NaruResult:
        ...


@dataclass
class LifecycleHooks:
    """Optional lifecycle hooks — exceptions are swallowed to protect main flow."""

    before_message: Callable[[str, str | None, str | None], None] | None = None
    after_message: Callable[[OrchestrationResult], None] | None = None
    on_error: Callable[[BaseException], None] | None = None


@dataclass
class AgentOrchestratorConfig(Generic[T]):
    """Configuration for AgentOrchestrator."""

    delegate: AgentChatDelegate
    delegates: dict[T, AgentChatDelegate] = field(default_factory=dict)
    intent_resolver: BaseIntentResolver[T] | None = None
    direct_executors: list[BaseDirectExecutor[T]] = field(default_factory=list)
    pending_state_manager: BasePendingStateManager | None = None
    session_state_store: BaseSessionStateStore | None = None
    channel_adapter: ChannelAdapter | None = None
    lifecycle_hooks: LifecycleHooks | None = None
    confirmation_classifier: Callable[[str], str] | None = None


class AgentOrchestrator(Generic[T]):
    """Wraps one or more AgentChatDelegate instances with 4-phase routing.

    Phase 0: Pending confirmation handling
    Phase 1: Intent resolution
    Phase 2: Direct execution (bypass LLM)
    Phase 3: Delegate routing

    AgentOrchestrator itself satisfies AgentChatDelegate, enabling nesting.
    """

    def __init__(self, config: AgentOrchestratorConfig[T]) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fire_hook(self, fn: Callable | None, *args: Any) -> None:
        """Call a lifecycle hook, silently swallowing any exception."""
        if fn is None:
            return
        try:
            fn(*args)
        except Exception:  # noqa: BLE001
            pass

    def _wrap_result(
        self,
        base_result: NaruResult,
        *,
        trace_id: str,
        phase_reached: OrchestrationPhase,
        orchestration_intent: OrchestratorIntent[T] | None,
        timings: OrchestrationTimings,
        direct_executor_used: str | None = None,
        delegate_used: str | None = None,
        pending_confirmation: PendingConfirmation | None = None,
        override_session_id: str | None = None,
    ) -> OrchestrationResult:
        """Wrap a NaruResult with orchestration metadata."""
        decision_trace = AgentDecisionTrace(
            trace_id=trace_id,
            phase_reached=phase_reached,
            intent_resolved=orchestration_intent,
            timings=timings,
            direct_executor_used=direct_executor_used,
            delegate_used=delegate_used,
        )
        return OrchestrationResult(
            content=base_result.content,
            blocked=base_result.blocked,
            usage=base_result.usage,
            intent=base_result.intent,
            tool_calls=base_result.tool_calls,
            timings=base_result.timings,
            session_id=override_session_id if override_session_id is not None else base_result.session_id,
            trace_id=base_result.trace_id,
            trace=base_result.trace,
            decision_trace=decision_trace,
            pending_confirmation=pending_confirmation,
            orchestration_intent=orchestration_intent,
        )

    def _get_hook(self, name: str) -> Callable | None:
        """Return a lifecycle hook by name, or None."""
        hooks = self._config.lifecycle_hooks
        if hooks is None:
            return None
        return getattr(hooks, name, None)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(
        self,
        message: str,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> OrchestrationResult:
        """Route a message through the 4-phase orchestration pipeline."""
        start_time = time.monotonic()
        trace_id = str(uuid.uuid4())

        timings = OrchestrationTimings()
        orchestration_intent: OrchestratorIntent[T] | None = None

        self._fire_hook(self._get_hook("before_message"), message, user_id, session_id)

        # Cache session state to avoid repeated fetches
        cached_session_state: AgentSessionState | None = None
        session_state_fetched = False

        try:
            # === Phase 0: Pending Confirmation ===
            if self._config.pending_state_manager and session_id:
                pending = self._config.pending_state_manager.get_pending(session_id)
                if pending is not None:
                    classifier = (
                        self._config.confirmation_classifier
                        or classify_confirmation_disposition
                    )
                    disposition = classifier(message)

                    if disposition in ("confirm", "reject"):
                        self._config.pending_state_manager.clear_pending(session_id)
                        timings.total = time.monotonic() - start_time
                        content = (
                            f"Confirmed: {pending.type}"
                            if disposition == "confirm"
                            else f"Rejected: {pending.type}"
                        )
                        base_result = NaruResult(
                            content=content,
                            blocked=False,
                            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                            timings={"total": timings.total},
                            session_id=session_id,
                            trace_id=trace_id,
                        )
                        result = self._wrap_result(
                            base_result,
                            trace_id=trace_id,
                            phase_reached="pending_confirmation",
                            orchestration_intent=None,
                            timings=timings,
                        )
                        self._fire_hook(self._get_hook("after_message"), result)
                        return result

                    # override — clear pending, continue normal flow
                    self._config.pending_state_manager.clear_pending(session_id)

            # === Phase 1: Intent Resolution ===
            if self._config.intent_resolver:
                intent_start = time.monotonic()
                if self._config.session_state_store and session_id and not session_state_fetched:
                    cached_session_state = self._config.session_state_store.get(session_id)
                    session_state_fetched = True

                orchestration_intent = self._config.intent_resolver.resolve(
                    IntentResolveInput(
                        message=message,
                        session_state=cached_session_state,
                    )
                )
                timings.intent_resolution = time.monotonic() - intent_start

            # === Phase 2: Direct Execution ===
            if self._config.direct_executors and orchestration_intent is not None:
                exec_start = time.monotonic()
                for executor in self._config.direct_executors:
                    if executor.can_handle(orchestration_intent):
                        exec_result = executor.execute(
                            message=message,
                            intent=orchestration_intent,
                            options={
                                "user_id": user_id,
                                "session_id": session_id,
                                "session_state": cached_session_state,
                            },
                        )
                        if exec_result is not None:
                            timings.direct_execution = time.monotonic() - exec_start
                            timings.total = time.monotonic() - start_time

                            result = self._wrap_result(
                                exec_result,
                                trace_id=trace_id,
                                phase_reached="direct_execution",
                                orchestration_intent=orchestration_intent,
                                timings=timings,
                                direct_executor_used=executor.name,
                            )
                            self._fire_hook(self._get_hook("after_message"), result)
                            return result

            # === Phase 3: Delegate Routing ===
            delegate_start = time.monotonic()
            selected_delegate: AgentChatDelegate = self._config.delegate
            selected_delegate_name = "default"

            if orchestration_intent is not None and self._config.delegates:
                mapped = self._config.delegates.get(orchestration_intent.object)  # type: ignore[arg-type]
                if mapped is not None:
                    selected_delegate = mapped
                    selected_delegate_name = str(orchestration_intent.object)

            # Fetch session state if not yet done (for post-delegate save)
            # NOTE: JS version injects sessionState into enrichedOptions passed
            # to the delegate. Python's AgentChatDelegate Protocol has a fixed
            # signature (message, user_id, session_id) matching NaruAgent.chat(),
            # so session state cannot be forwarded as a parameter. Delegates that
            # need session state should read from the store directly.
            if self._config.session_state_store and session_id and not session_state_fetched:
                cached_session_state = self._config.session_state_store.get(session_id)
                session_state_fetched = True

            delegate_result = selected_delegate.chat(
                message,
                user_id=user_id,
                session_id=session_id,
            )
            timings.delegate = time.monotonic() - delegate_start
            timings.total = time.monotonic() - start_time

            # Update session state if applicable
            if self._config.session_state_store and session_id and delegate_result.session_id:
                new_state = AgentSessionState(
                    session_id=session_id,
                    last_presented_entities=cached_session_state.last_presented_entities
                    if cached_session_state
                    else [],
                    metadata=cached_session_state.metadata if cached_session_state else {},
                    updated_at=time.time(),
                )
                self._config.session_state_store.save(session_id, new_state)

            result = self._wrap_result(
                delegate_result,
                trace_id=trace_id,
                phase_reached="delegate",
                orchestration_intent=orchestration_intent,
                timings=timings,
                delegate_used=selected_delegate_name,
                override_session_id=session_id or delegate_result.session_id,
            )
            self._fire_hook(self._get_hook("after_message"), result)
            return result

        except Exception as exc:
            self._fire_hook(self._get_hook("on_error"), exc)
            raise

    def process_channel(self, raw_input: Any) -> Any:
        """Process channel-specific raw input through the configured channel adapter."""
        if self._config.channel_adapter is None:
            raise ValueError("No channel_adapter configured")

        channel_message: ChannelMessage = self._config.channel_adapter.parse_incoming(raw_input)

        result = self.chat(
            channel_message.text,
            user_id=channel_message.user_id,
            session_id=channel_message.session_id,
        )

        return self._config.channel_adapter.format_outgoing(result)
