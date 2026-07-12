"""Request-scoped sink for streaming LLM text deltas out of the gateway.

The gateway is a shared library used by every usage_type. A sink is installed
only by the transport that actually streams (Rizo SSE); when no sink is
installed the gateway's behaviour is bit-for-bit unchanged.
"""
from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import Protocol


class DeltaSink(Protocol):
    """Receives text deltas as the upstream LLM produces them."""

    def push(self, text: str) -> None:
        """Append newly generated text."""

    def reset(self) -> None:
        """Discard everything pushed since the last reset (the client is told
        to clear its bubble). Called when an attempt's output is thrown away:
        a cross-provider fallback retry, or a call agno discards because it
        finished with tool_calls."""

    @property
    def pushed_since_reset(self) -> bool:
        """True if push() has been called since construction or the last reset."""


_delta_sink: ContextVar[DeltaSink | None] = ContextVar("naru_delta_sink", default=None)


def current_delta_sink() -> DeltaSink | None:
    return _delta_sink.get()


@contextlib.contextmanager
def use_delta_sink(sink: DeltaSink | None):
    token = _delta_sink.set(sink)
    try:
        yield sink
    finally:
        _delta_sink.reset(token)
