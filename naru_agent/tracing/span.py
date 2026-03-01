from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Span:
    """A single unit of work within a Trace."""

    span_id: str
    trace_id: str
    name: str  # "llm_call" | "tool_call" | "memory_query" | "intent_classify" | "knowledge_query" | "agent_run"
    start_time: float
    end_time: float | None = None
    input: dict = field(default_factory=dict)
    output: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    status: str = "ok"  # "ok" | "error"
    error: str | None = None

    @classmethod
    def create(cls, trace_id: str, name: str, **kwargs) -> "Span":
        return cls(
            span_id=str(uuid.uuid4()),
            trace_id=trace_id,
            name=name,
            start_time=time.time(),
            **kwargs,
        )

    @property
    def duration_ms(self) -> float | None:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000

    def finish(self, status: str = "ok", error: str | None = None) -> None:
        self.end_time = time.time()
        self.status = status
        if error:
            self.error = error

    def to_dict(self) -> dict:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "input": self.input,
            "output": self.output,
            "metadata": self.metadata,
            "status": self.status,
            "error": self.error,
        }
