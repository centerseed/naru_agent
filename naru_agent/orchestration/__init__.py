"""naru_agent.orchestration — 4-phase routing + multi-agent orchestration."""

from naru_agent.orchestration.channel import ChannelAdapter, ChannelMessage
from naru_agent.orchestration.executor import BaseDirectExecutor
from naru_agent.orchestration.intent import (
    BaseIntentResolver,
    DeterministicIntentResolver,
    DeterministicPattern,
    IntentResolveInput,
    LLMFallbackIntentResolver,
    OrchestratorIntent,
)
from naru_agent.orchestration.orchestrator import (
    AgentChatDelegate,
    AgentOrchestrator,
    AgentOrchestratorConfig,
    LifecycleHooks,
)
from naru_agent.orchestration.pending import (
    BasePendingStateManager,
    ConfirmationDisposition,
    InMemoryPendingStateManager,
    PendingState,
    classify_confirmation_disposition,
)
from naru_agent.orchestration.result import OrchestrationResult, PendingConfirmation
from naru_agent.orchestration.session_state import (
    AgentSessionState,
    BaseSessionStateStore,
    InMemorySessionStateStore,
)
from naru_agent.orchestration.trace import (
    AgentDecisionTrace,
    OrchestrationPhase,
    OrchestrationTimings,
)

__all__ = [
    # orchestrator
    "AgentChatDelegate",
    "AgentOrchestrator",
    "AgentOrchestratorConfig",
    "LifecycleHooks",
    # intent
    "BaseIntentResolver",
    "DeterministicIntentResolver",
    "DeterministicPattern",
    "IntentResolveInput",
    "LLMFallbackIntentResolver",
    "OrchestratorIntent",
    # executor
    "BaseDirectExecutor",
    # channel
    "ChannelAdapter",
    "ChannelMessage",
    # pending
    "BasePendingStateManager",
    "ConfirmationDisposition",
    "InMemoryPendingStateManager",
    "PendingState",
    "classify_confirmation_disposition",
    # result
    "OrchestrationResult",
    "PendingConfirmation",
    # session_state
    "AgentSessionState",
    "BaseSessionStateStore",
    "InMemorySessionStateStore",
    # trace
    "AgentDecisionTrace",
    "OrchestrationPhase",
    "OrchestrationTimings",
]
