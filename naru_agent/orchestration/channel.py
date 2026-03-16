"""ChannelAdapter — abstracts channel-specific I/O transformation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from naru_agent.orchestration.result import OrchestrationResult


@dataclass
class ChannelMessage:
    """Normalised input from any channel."""

    text: str
    user_id: str | None = None
    session_id: str | None = None
    raw: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ChannelAdapter(Protocol):
    """Abstracts channel-specific I/O transformation.

    Implementations translate raw channel payloads to/from the orchestrator's
    standard message/result format.
    """

    def parse_incoming(self, input: Any) -> ChannelMessage:  # noqa: A002
        """Transform raw channel input into a ChannelMessage."""
        ...

    def format_outgoing(self, result: OrchestrationResult) -> Any:
        """Transform an OrchestrationResult into a channel-specific payload."""
        ...
