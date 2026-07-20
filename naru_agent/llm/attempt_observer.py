"""Invocation-local, privacy-safe observation of physical provider attempts."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class LLMAttemptObservation:
    provider: str
    model: str
    outcome: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cost_microusd: int
    fallback_reason: str | None


AttemptObserver = Callable[[LLMAttemptObservation], object]
_CURRENT_OBSERVER: ContextVar[AttemptObserver | None] = ContextVar(
    "naru_llm_attempt_observer", default=None
)


@contextmanager
def use_attempt_observer(observer: AttemptObserver):
    token = _CURRENT_OBSERVER.set(observer)
    try:
        yield
    finally:
        _CURRENT_OBSERVER.reset(token)


def observe_attempt(observation: LLMAttemptObservation) -> None:
    observer = _CURRENT_OBSERVER.get()
    if observer is not None:
        observer(observation)
