from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from naru_agent.compression.base import CompressedSummary
from naru_agent.compression.compressor import ContextCompressor
from naru_agent.compression.memory_store import InMemorySummaryStore


def _run(coro):
    return asyncio.run(coro)


@dataclass
class FakeMessage:
    role: str = "user"
    content: str = ""


@dataclass
class FakeRun:
    messages: list[FakeMessage] = field(default_factory=list)


@dataclass
class FakeSession:
    runs: list[FakeRun] = field(default_factory=list)


class FakeDb:
    def __init__(self, sessions: dict[str, FakeSession] | None = None):
        self._sessions = sessions or {}

    def get_session(self, session_id: str, **kwargs):
        return self._sessions.get(session_id)


class TestContextCompressor:
    def _make_compressor(self, store=None, threshold=5, keep_last=5):
        store = store or InMemorySummaryStore()
        return ContextCompressor(
            summary_store=store,
            summary_model="test-model",
            keep_last_rounds=keep_last,
            threshold_rounds=threshold,
        ), store

    def _make_agent_with_runs(self, session_id: str, num_runs: int):
        runs = []
        for i in range(num_runs):
            runs.append(FakeRun(messages=[
                FakeMessage(role="user", content=f"Question {i+1}"),
                FakeMessage(role="assistant", content=f"Answer {i+1}"),
            ]))
        session = FakeSession(runs=runs)
        agent = MagicMock()
        agent.db = FakeDb({session_id: session})
        return agent

    def test_no_compression_below_threshold(self):
        compressor, store = self._make_compressor(threshold=5)
        agent = self._make_agent_with_runs("s1", 5)

        with patch("litellm.completion") as mock_completion:
            compressor.maybe_compress("s1", agent)
            mock_completion.assert_not_called()

        assert _run(store.get("s1")) is None

    def test_compression_triggers_above_threshold(self):
        compressor, store = self._make_compressor(threshold=5, keep_last=5)
        agent = self._make_agent_with_runs("s1", 6)

        with patch("litellm.completion") as mock_completion:
            mock_resp = MagicMock()
            mock_resp.choices = [MagicMock()]
            mock_resp.choices[0].message.content = "Summary of round 1"
            mock_completion.return_value = mock_resp

            compressor.maybe_compress("s1", agent)
            mock_completion.assert_called_once()

        summary = _run(store.get("s1"))
        assert summary is not None
        assert summary.summary_text == "Summary of round 1"
        assert summary.compressed_through_run == 1

    def test_compression_at_round_10(self):
        compressor, store = self._make_compressor(threshold=5, keep_last=5)
        agent = self._make_agent_with_runs("s1", 10)

        with patch("litellm.completion") as mock_completion:
            mock_resp = MagicMock()
            mock_resp.choices = [MagicMock()]
            mock_resp.choices[0].message.content = "Summary of rounds 1-5"
            mock_completion.return_value = mock_resp

            compressor.maybe_compress("s1", agent)

        summary = _run(store.get("s1"))
        assert summary.compressed_through_run == 5

    def test_skips_if_already_compressed(self):
        store = InMemorySummaryStore()
        existing = CompressedSummary(
            summary_text="existing",
            compressed_through_run=3,
            model_used="test",
        )
        _run(store.save("s1", existing))

        compressor, _ = self._make_compressor(store=store, threshold=5, keep_last=5)
        # 8 runs => compress_through = 3, same as existing
        agent = self._make_agent_with_runs("s1", 8)

        with patch("litellm.completion") as mock_completion:
            compressor.maybe_compress("s1", agent)
            mock_completion.assert_not_called()

    def test_recompresses_when_more_runs(self):
        store = InMemorySummaryStore()
        existing = CompressedSummary(
            summary_text="old",
            compressed_through_run=1,
            model_used="test",
        )
        _run(store.save("s1", existing))

        compressor, _ = self._make_compressor(store=store, threshold=5, keep_last=5)
        # 8 runs => compress_through = 3, > existing's 1
        agent = self._make_agent_with_runs("s1", 8)

        with patch("litellm.completion") as mock_completion:
            mock_resp = MagicMock()
            mock_resp.choices = [MagicMock()]
            mock_resp.choices[0].message.content = "Updated summary"
            mock_completion.return_value = mock_resp

            compressor.maybe_compress("s1", agent)

        summary = _run(store.get("s1"))
        assert summary.summary_text == "Updated summary"
        assert summary.compressed_through_run == 3

    def test_get_summary_sync_returns_none_when_empty(self):
        compressor, _ = self._make_compressor()
        assert compressor.get_summary_sync("nonexistent") is None

    def test_get_summary_sync_returns_existing(self):
        store = InMemorySummaryStore()
        summary = CompressedSummary(
            summary_text="test",
            compressed_through_run=2,
            model_used="m",
        )
        _run(store.save("s1", summary))
        compressor, _ = self._make_compressor(store=store)
        result = compressor.get_summary_sync("s1")
        assert result is not None
        assert result.summary_text == "test"

    def test_extract_conversation(self):
        compressor, _ = self._make_compressor()
        runs = [
            FakeRun(messages=[
                FakeMessage(role="user", content="Hi"),
                FakeMessage(role="assistant", content="Hello"),
            ]),
            FakeRun(messages=[
                FakeMessage(role="user", content="How?"),
                FakeMessage(role="assistant", content="Fine"),
            ]),
        ]
        text = compressor._extract_conversation(runs)
        assert "user: Hi" in text
        assert "assistant: Hello" in text
        assert "user: How?" in text

    def test_no_agent_db(self):
        compressor, store = self._make_compressor(threshold=5)
        agent = MagicMock()
        agent.db = None
        compressor.maybe_compress("s1", agent)
        assert _run(store.get("s1")) is None

    def test_llm_failure_does_not_crash(self):
        compressor, store = self._make_compressor(threshold=5, keep_last=5)
        agent = self._make_agent_with_runs("s1", 7)

        with patch("litellm.completion") as mock_completion:
            mock_completion.side_effect = Exception("LLM down")
            compressor.maybe_compress("s1", agent)

        assert _run(store.get("s1")) is None
