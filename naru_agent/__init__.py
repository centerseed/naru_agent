import warnings

from naru_agent.agent import Agent, NaruAgent, NaruResult
from naru_agent.tracing import (
    Trace,
    Span,
    TraceCollector,
    BaseTraceExporter,
    JSONLTraceExporter,
)
from naru_agent.tools.base import BaseTool, tool
from naru_agent.skills import BaseSkill, SkillContext, SkillResult
from naru_agent.skills.base import skill
from naru_agent.skills.selectors import BaseSkillSelector, KeywordSkillSelector, LLMSkillSelector
from naru_agent.memory.manager import MemoryManager
from naru_agent.guardrails.base import BaseGuardrail, GuardrailResult
from naru_agent.events import EventBus
from naru_agent.tool_selection.base import BaseToolSelector, ToolSelectionResult
from naru_agent.streaming import (
    StreamEvent,
    TextDeltaEvent,
    ToolCallStartEvent,
    ToolResultEvent,
    DoneEvent,
    ErrorEvent,
)
from naru_agent.session import BaseSessionStore, InMemorySessionStore
from naru_agent.compression import (
    BaseSummaryStore,
    CompressedSummary,
    ContextCompressor,
    InMemorySummaryStore,
)
from naru_agent.knowledge import BaseKnowledgeStore, KnowledgeResult
from naru_agent.intent import (
    BaseIntentClassifier,
    IntentResult,
    LLMIntentClassifier,
    BaseToolCallingClassifier,
    LLMToolCallingClassifier,
    ToolCallingResult,
)

_RUNNER_WARNED = False


def __getattr__(name: str):
    """Lazy module attributes with deprecation warnings."""
    global _RUNNER_WARNED
    if name == "Runner":
        if not _RUNNER_WARNED:
            warnings.warn(
                "Runner is deprecated. Use NaruAgent instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            _RUNNER_WARNED = True
        from naru_agent.runner import Runner
        return Runner
    if name == "ChromaKnowledgeStore":
        from naru_agent.knowledge.chroma_store import ChromaKnowledgeStore
        return ChromaKnowledgeStore
    if name == "ChunkContextualizer":
        from naru_agent.knowledge.contextualizer import ChunkContextualizer
        return ChunkContextualizer
    if name == "EmbeddingSkillSelector":
        from naru_agent.skills.selectors import EmbeddingSkillSelector
        return EmbeddingSkillSelector
    raise AttributeError(f"module 'naru_agent' has no attribute {name!r}")


__all__ = [
    # New API
    "NaruAgent",
    "NaruResult",
    # Tracing
    "Trace",
    "Span",
    "TraceCollector",
    "BaseTraceExporter",
    "JSONLTraceExporter",
    # Knowledge
    "BaseKnowledgeStore",
    "KnowledgeResult",
    "ChromaKnowledgeStore",
    "ChunkContextualizer",
    # Intent
    "BaseIntentClassifier",
    "IntentResult",
    "LLMIntentClassifier",
    "BaseToolCallingClassifier",
    "LLMToolCallingClassifier",
    "ToolCallingResult",
    # Legacy (kept for backward compat)
    "Agent",
    "Runner",
    "BaseTool",
    "tool",
    "MemoryManager",
    "BaseGuardrail",
    "GuardrailResult",
    "EventBus",
    "BaseToolSelector",
    "ToolSelectionResult",
    # Streaming
    "StreamEvent",
    "TextDeltaEvent",
    "ToolCallStartEvent",
    "ToolResultEvent",
    "DoneEvent",
    "ErrorEvent",
    # Session
    "BaseSessionStore",
    "InMemorySessionStore",
    # Skills
    "BaseSkill",
    "SkillContext",
    "SkillResult",
    "skill",
    "BaseSkillSelector",
    "KeywordSkillSelector",
    "LLMSkillSelector",
    # Compression
    "BaseSummaryStore",
    "CompressedSummary",
    "ContextCompressor",
    "InMemorySummaryStore",
]

try:
    from naru_agent.orchestration import (
        AgentChatDelegate,
        AgentOrchestrator,
        AgentOrchestratorConfig,
        AgentDecisionTrace,
        AgentSessionState,
        BaseDirectExecutor,
        BaseIntentResolver,
        BasePendingStateManager,
        BaseSessionStateStore,
        ChannelAdapter,
        ChannelMessage,
        ConfirmationDisposition,
        DeterministicIntentResolver,
        DeterministicPattern,
        InMemoryPendingStateManager,
        InMemorySessionStateStore,
        IntentResolveInput,
        LifecycleHooks,
        LLMFallbackIntentResolver,
        OrchestrationPhase,
        OrchestrationResult,
        OrchestrationTimings,
        OrchestratorIntent,
        PendingConfirmation,
        PendingState,
        classify_confirmation_disposition,
    )

    __all__ += [
        "AgentChatDelegate",
        "AgentOrchestrator",
        "AgentOrchestratorConfig",
        "AgentDecisionTrace",
        "AgentSessionState",
        "BaseDirectExecutor",
        "BaseIntentResolver",
        "BasePendingStateManager",
        "BaseSessionStateStore",
        "ChannelAdapter",
        "ChannelMessage",
        "ConfirmationDisposition",
        "DeterministicIntentResolver",
        "DeterministicPattern",
        "InMemoryPendingStateManager",
        "InMemorySessionStateStore",
        "IntentResolveInput",
        "LifecycleHooks",
        "LLMFallbackIntentResolver",
        "OrchestrationPhase",
        "OrchestrationResult",
        "OrchestrationTimings",
        "OrchestratorIntent",
        "PendingConfirmation",
        "PendingState",
        "classify_confirmation_disposition",
    ]
except ImportError:
    pass

try:
    from naru_agent.memory.mem0_manager import Mem0MemoryManager

    __all__.append("Mem0MemoryManager")
except ImportError:
    pass

try:
    from naru_agent.tool_selection.embedding import EmbeddingToolSelector, litellm_embed_fn

    __all__ += ["EmbeddingToolSelector", "litellm_embed_fn"]
except ImportError:
    pass

try:
    from naru_agent.session.redis_store import RedisSessionStore

    __all__.append("RedisSessionStore")
except ImportError:
    pass

try:
    from naru_agent.compression.redis_store import RedisSummaryStore

    __all__.append("RedisSummaryStore")
except ImportError:
    pass
