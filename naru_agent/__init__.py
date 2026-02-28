from naru_agent.agent import Agent
from naru_agent.runner import Runner
from naru_agent.tools.base import BaseTool, tool
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

__all__ = [
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
]

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
