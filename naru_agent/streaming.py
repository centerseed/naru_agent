from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

# NOTE: This module is deprecated. Agno provides native streaming via NaruAgent.
from typing import Literal, Union

logger = logging.getLogger(__name__)


@dataclass
class StreamChunk:
    """Raw chunk from LLM provider (internal use)."""

    delta_text: str | None = None
    tool_call_deltas: list[dict] = field(default_factory=list)
    finish_reason: str | None = None  # "stop" | "tool_calls" | None
    usage: dict | None = None


@dataclass
class TextDeltaEvent:
    type: Literal["text_delta"] = "text_delta"
    delta: str = ""
    snapshot: str = ""


@dataclass
class ToolCallStartEvent:
    type: Literal["tool_call_start"] = "tool_call_start"
    tool_call_id: str = ""
    name: str = ""
    arguments: dict = field(default_factory=dict)


@dataclass
class ToolResultEvent:
    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str = ""
    name: str = ""
    result: str = ""


@dataclass
class DoneEvent:
    type: Literal["done"] = "done"
    content: str = ""
    usage: dict = field(default_factory=dict)


@dataclass
class ErrorEvent:
    type: Literal["error"] = "error"
    error: str = ""


StreamEvent = Union[TextDeltaEvent, ToolCallStartEvent, ToolResultEvent, DoneEvent, ErrorEvent]


def _accumulate_tool_call_chunks(
    accumulated: dict[int, dict],
    deltas: list[dict],
) -> None:
    """Merge partial tool call chunks by index into accumulated dict."""
    for delta in deltas:
        idx = delta.get("index", 0)
        is_new = idx not in accumulated
        if is_new:
            accumulated[idx] = {
                "id": "",
                "name": "",
                "arguments": "",
            }
        entry = accumulated[idx]
        if delta.get("id"):
            entry["id"] = delta["id"]
        if delta.get("name"):
            entry["name"] += delta["name"]
        if delta.get("arguments"):
            entry["arguments"] += delta["arguments"]


def _finalize_tool_calls(accumulated: dict[int, dict]) -> list[dict]:
    """Convert accumulated partial tool calls into complete tool call list."""
    result = []
    for idx in sorted(accumulated.keys()):
        entry = accumulated[idx]
        try:
            arguments = json.loads(entry["arguments"]) if entry["arguments"] else {}
        except json.JSONDecodeError:
            logger.warning(
                "Failed to parse tool call arguments for '%s': %s",
                entry["name"], entry["arguments"],
            )
            arguments = {}
        result.append({
            "id": entry["id"],
            "name": entry["name"],
            "arguments": arguments,
        })
    return result
