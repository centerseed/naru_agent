from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field

from naru_agent.tracing.span import Span


@dataclass
class Trace:
    """Complete record of a single NaruAgent.chat() call."""

    trace_id: str
    thread_id: str | None  # = session_id，用於 Thread 追蹤
    user_id: str | None
    start_time: float
    end_time: float | None = None
    input: str = ""
    output: str = ""
    blocked: bool = False
    usage: dict = field(default_factory=dict)
    intent: dict | None = None
    tool_calls: list[str] = field(default_factory=list)
    spans: list[Span] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        message: str,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> "Trace":
        return cls(
            trace_id=str(uuid.uuid4()),
            thread_id=session_id,
            user_id=user_id,
            start_time=time.time(),
            input=message,
        )

    @property
    def duration_ms(self) -> float | None:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "thread_id": self.thread_id,
            "user_id": self.user_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "input": self.input,
            "output": self.output,
            "blocked": self.blocked,
            "usage": self.usage,
            "intent": self.intent,
            "tool_calls": self.tool_calls,
            "spans": [s.to_dict() for s in self.spans],
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
