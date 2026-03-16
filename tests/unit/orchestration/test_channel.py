"""@ac8 — ChannelAdapter message transformation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from naru_agent.agent import NaruResult
from naru_agent.orchestration.channel import ChannelAdapter, ChannelMessage
from naru_agent.orchestration.orchestrator import (
    AgentOrchestrator,
    AgentOrchestratorConfig,
)
from naru_agent.orchestration.result import OrchestrationResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class SimpleChannelAdapter:
    """Minimal ChannelAdapter: dict in → dict out."""

    def parse_incoming(self, input: dict) -> ChannelMessage:  # noqa: A002
        return ChannelMessage(
            text=input["text"],
            user_id=input.get("user_id"),
            session_id=input.get("session_id"),
            raw=input,
        )

    def format_outgoing(self, result: OrchestrationResult) -> dict:
        return {"reply": result.content, "session_id": result.session_id}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestChannelAdapter:
    """@ac8 — channel adapter I/O transformation."""

    def test_parse_incoming_extracts_text(self):
        adapter = SimpleChannelAdapter()
        msg = adapter.parse_incoming({"text": "hello"})
        assert msg.text == "hello"

    def test_parse_incoming_extracts_ids(self):
        adapter = SimpleChannelAdapter()
        msg = adapter.parse_incoming({"text": "hi", "user_id": "u1", "session_id": "s1"})
        assert msg.user_id == "u1"
        assert msg.session_id == "s1"

    def test_format_outgoing_maps_content(self):
        adapter = SimpleChannelAdapter()
        result = OrchestrationResult(content="response", session_id="s1")
        output = adapter.format_outgoing(result)
        assert output["reply"] == "response"
        assert output["session_id"] == "s1"

    def test_process_channel_full_round_trip(self):
        delegate = MagicMock()
        delegate.chat.return_value = NaruResult(content="processed", session_id="s1")
        adapter = SimpleChannelAdapter()
        config = AgentOrchestratorConfig(delegate=delegate, channel_adapter=adapter)
        orch = AgentOrchestrator(config)

        output = orch.process_channel({"text": "hello", "session_id": "s1"})
        assert output["reply"] == "processed"

    def test_process_channel_raises_without_adapter(self):
        delegate = MagicMock()
        delegate.chat.return_value = NaruResult(content="hi")
        orch = AgentOrchestrator(AgentOrchestratorConfig(delegate=delegate))
        with pytest.raises(ValueError, match="channel_adapter"):
            orch.process_channel({"text": "hi"})

    def test_channel_message_raw_preserved(self):
        adapter = SimpleChannelAdapter()
        raw = {"text": "test", "extra_field": 42}
        msg = adapter.parse_incoming(raw)
        assert msg.raw is raw
