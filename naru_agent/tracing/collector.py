from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from naru_agent.tracing.span import Span
from naru_agent.tracing.trace import Trace

if TYPE_CHECKING:
    from naru_agent.agent import NaruResult
    from naru_agent.events import EventBus

logger = logging.getLogger(__name__)


class TraceCollector:
    """掛入 EventBus，將 events 組裝成 Trace。"""

    def __init__(self, event_bus: "EventBus") -> None:
        self._current_trace: Trace | None = None
        self._pending_spans: dict[str, Span] = {}  # span_id → Span
        self._last_tool_span_ids: dict[str, str] = {}  # tool_name → span_id

        event_bus.on("before_llm_call", self._on_before_llm_call)
        event_bus.on("after_llm_call", self._on_after_llm_call)
        event_bus.on("before_tool_call", self._on_before_tool_call)
        event_bus.on("after_tool_call", self._on_after_tool_call)
        event_bus.on("memory_retrieved", self._on_memory_retrieved)
        event_bus.on("intent_classified", self._on_intent_classified)
        event_bus.on("knowledge_retrieved", self._on_knowledge_retrieved)
        event_bus.on("tool_calling_classified", self._on_tool_calling_classified)

    def start_trace(
        self,
        message: str,
        user_id: str | None,
        session_id: str | None,
    ) -> str:
        """開始新 trace，回傳 trace_id。"""
        self._current_trace = Trace.create(message, user_id, session_id)
        self._pending_spans.clear()
        self._last_tool_span_ids.clear()
        return self._current_trace.trace_id

    def end_trace(self, result: "NaruResult") -> Trace:
        """結束 trace，附加最終 result 資料，回傳完整 Trace。"""
        if self._current_trace is None:
            # Fallback: create an empty trace
            self._current_trace = Trace.create(result.content or "")

        trace = self._current_trace
        trace.end_time = time.time()
        trace.output = result.content
        trace.blocked = result.blocked
        trace.usage = result.usage
        trace.tool_calls = result.tool_calls
        if result.intent is not None:
            trace.intent = {
                "needs_knowledge": result.intent.needs_knowledge,
                "needs_tools": result.intent.needs_tools,
                "raw": result.intent.raw,
            }

        self._current_trace = None
        self._pending_spans.clear()
        self._last_tool_span_ids.clear()
        return trace

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_before_llm_call(self, data: dict) -> None:
        if self._current_trace is None:
            return
        span = Span.create(
            trace_id=self._current_trace.trace_id,
            name="llm_call",
            metadata={
                "iteration": data.get("iteration"),
                "message_count": data.get("message_count"),
            },
        )
        self._pending_spans[f"llm_{data.get('iteration', 0)}"] = span

    def _on_after_llm_call(self, data: dict) -> None:
        if self._current_trace is None:
            return
        key = f"llm_{data.get('iteration', 0)}"
        span = self._pending_spans.pop(key, None)
        if span is None:
            span = Span.create(
                trace_id=self._current_trace.trace_id,
                name="llm_call",
            )
        span.finish()
        span.output = {
            "content": data.get("response_content", ""),
            "tool_calls": data.get("tool_calls", []),
        }
        span.metadata.update({
            "model": data.get("model"),
            "usage": data.get("usage", {}),
            "latency_ms": data.get("latency_ms"),
            "has_tool_calls": data.get("has_tool_calls", False),
        })
        self._current_trace.spans.append(span)

    def _on_before_tool_call(self, data: dict) -> None:
        if self._current_trace is None:
            return
        name = data.get("name", "unknown")
        span = Span.create(
            trace_id=self._current_trace.trace_id,
            name="tool_call",
            input={"arguments": data.get("arguments", {})},
            metadata={"tool_name": name},
        )
        self._pending_spans[span.span_id] = span
        # Stash span_id so after_tool_call can find it by tool name
        self._last_tool_span_ids[name] = span.span_id

    def _on_after_tool_call(self, data: dict) -> None:
        if self._current_trace is None:
            return
        tool_name = data.get("tool", "unknown")
        span_id = self._last_tool_span_ids.pop(tool_name, None)
        span = self._pending_spans.pop(span_id, None) if span_id else None
        if span is None:
            span = Span.create(
                trace_id=self._current_trace.trace_id,
                name="tool_call",
                metadata={"tool_name": tool_name},
            )
        span.finish()
        result = data.get("result", "")
        if isinstance(result, str) and len(result) > 2000:
            result = result[:2000] + "...[truncated]"
        span.output = {"result": result}
        span.metadata.update({
            "latency_ms": data.get("latency_ms"),
            "result_length": data.get("result_length"),
        })
        self._current_trace.spans.append(span)

    def _on_memory_retrieved(self, data: dict) -> None:
        if self._current_trace is None:
            return
        span = Span.create(
            trace_id=self._current_trace.trace_id,
            name="memory_query",
            input={"query": data.get("query", "")},
            output={"items_count": data.get("items_count", 0)},
            metadata={
                "user_id": data.get("user_id"),
                "latency_ms": data.get("latency_ms"),
            },
        )
        span.finish()
        self._current_trace.spans.append(span)

    def _on_intent_classified(self, data: dict) -> None:
        if self._current_trace is None:
            return
        result = data.get("result")
        span = Span.create(
            trace_id=self._current_trace.trace_id,
            name="intent_classify",
            output={
                "needs_knowledge": getattr(result, "needs_knowledge", None),
                "needs_tools": getattr(result, "needs_tools", None),
                "raw": getattr(result, "raw", None),
            } if result else {},
            metadata={"latency_ms": data.get("latency_ms")},
        )
        span.finish()
        self._current_trace.spans.append(span)

    def _on_tool_calling_classified(self, data: dict) -> None:
        if self._current_trace is None:
            return
        span = Span.create(
            trace_id=self._current_trace.trace_id,
            name="tool_calling_classify",
            output={"tools_called": data.get("tools_called", [])},
            metadata={
                "usage": data.get("usage", {}),
                "latency_ms": data.get("latency_ms"),
            },
        )
        span.finish()
        self._current_trace.spans.append(span)

    def _on_knowledge_retrieved(self, data: dict) -> None:
        if self._current_trace is None:
            return
        span = Span.create(
            trace_id=self._current_trace.trace_id,
            name="knowledge_query",
            input={"query": data.get("query", "")},
            output={"chunks_count": data.get("chunks_count", 0)},
            metadata={"latency_ms": data.get("latency_ms")},
        )
        span.finish()
        self._current_trace.spans.append(span)

