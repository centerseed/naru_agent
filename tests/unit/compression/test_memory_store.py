from __future__ import annotations

import asyncio
import pytest

from naru_agent.compression.base import CompressedSummary
from naru_agent.compression.memory_store import InMemorySummaryStore


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _run(loop, coro):
    return loop.run_until_complete(coro)


class TestInMemorySummaryStore:
    def test_get_returns_none_when_empty(self, event_loop):
        store = InMemorySummaryStore()
        assert _run(event_loop, store.get("s1")) is None

    def test_save_and_get(self, event_loop):
        store = InMemorySummaryStore()
        summary = CompressedSummary(
            summary_text="test summary",
            compressed_through_run=3,
            model_used="test-model",
        )
        _run(event_loop, store.save("s1", summary))
        result = _run(event_loop, store.get("s1"))
        assert result is not None
        assert result.summary_text == "test summary"
        assert result.compressed_through_run == 3
        assert result.model_used == "test-model"

    def test_get_returns_deep_copy(self, event_loop):
        store = InMemorySummaryStore()
        summary = CompressedSummary(summary_text="original", compressed_through_run=1)
        _run(event_loop, store.save("s1", summary))
        r1 = _run(event_loop, store.get("s1"))
        r2 = _run(event_loop, store.get("s1"))
        assert r1 is not r2
        r1.summary_text = "mutated"
        r2 = _run(event_loop, store.get("s1"))
        assert r2.summary_text == "original"

    def test_delete(self, event_loop):
        store = InMemorySummaryStore()
        summary = CompressedSummary(summary_text="to delete", compressed_through_run=2)
        _run(event_loop, store.save("s1", summary))
        _run(event_loop, store.delete("s1"))
        assert _run(event_loop, store.get("s1")) is None

    def test_delete_nonexistent(self, event_loop):
        store = InMemorySummaryStore()
        _run(event_loop, store.delete("nonexistent"))

    def test_overwrite(self, event_loop):
        store = InMemorySummaryStore()
        s1 = CompressedSummary(summary_text="v1", compressed_through_run=1)
        s2 = CompressedSummary(summary_text="v2", compressed_through_run=3)
        _run(event_loop, store.save("s1", s1))
        _run(event_loop, store.save("s1", s2))
        result = _run(event_loop, store.get("s1"))
        assert result.summary_text == "v2"
        assert result.compressed_through_run == 3

    def test_multiple_sessions(self, event_loop):
        store = InMemorySummaryStore()
        s1 = CompressedSummary(summary_text="session 1", compressed_through_run=1)
        s2 = CompressedSummary(summary_text="session 2", compressed_through_run=2)
        _run(event_loop, store.save("a", s1))
        _run(event_loop, store.save("b", s2))
        assert _run(event_loop, store.get("a")).summary_text == "session 1"
        assert _run(event_loop, store.get("b")).summary_text == "session 2"
