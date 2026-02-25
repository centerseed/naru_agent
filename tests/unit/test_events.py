"""EventBus 單元測試"""
from __future__ import annotations

import pytest

from naru_agent.events import EventBus


def test_event_handler_called_on_emit():
    bus = EventBus()
    calls = []
    bus.on("my_event", lambda data: calls.append(data))
    bus.emit("my_event", {"key": "value"})
    assert len(calls) == 1
    assert calls[0] == {"key": "value"}


def test_multiple_handlers_all_called():
    bus = EventBus()
    results = []
    bus.on("ev", lambda d: results.append("handler1"))
    bus.on("ev", lambda d: results.append("handler2"))
    bus.emit("ev", {})
    assert results == ["handler1", "handler2"]


def test_handler_removed_with_off():
    bus = EventBus()
    calls = []

    def handler(data):
        calls.append(data)

    bus.on("ev", handler)
    bus.off("ev", handler)
    bus.emit("ev", "test")
    assert calls == []


def test_unknown_event_does_not_raise():
    bus = EventBus()
    # 未登記的事件不應拋出例外
    bus.emit("nonexistent_event", {"data": 123})


def test_event_data_passed_to_handler():
    bus = EventBus()
    received = []
    bus.on("data_event", lambda d: received.append(d))
    bus.emit("data_event", {"iteration": 3, "count": 10})
    assert received[0]["iteration"] == 3
    assert received[0]["count"] == 10
