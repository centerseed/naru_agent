from __future__ import annotations

from abc import ABC, abstractmethod

from naru_agent.tracing.trace import Trace


class BaseTraceExporter(ABC):
    """Abstract base class for trace exporters."""

    @abstractmethod
    def export(self, trace: Trace) -> None:
        """Export a completed trace."""
        ...
