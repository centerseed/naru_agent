from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)


class EventBus:
    """Lightweight event bus for hooks and monitoring.

    Usage:
        bus = EventBus()
        bus.on("before_llm_call", lambda data: print(f"Calling LLM: {data}"))
        bus.emit("before_llm_call", {"model": "gemini-2.5-flash-lite"})
    """

    def __init__(self):
        self._handlers: dict[str, list[Callable]] = defaultdict(list)

    def on(self, event: str, handler: Callable) -> None:
        self._handlers[event].append(handler)

    def off(self, event: str, handler: Callable) -> None:
        if event in self._handlers:
            self._handlers[event] = [h for h in self._handlers[event] if h != handler]

    def emit(self, event: str, data: Any = None) -> None:
        for handler in self._handlers.get(event, []):
            try:
                handler(data)
            except Exception:
                logger.exception(f"Error in event handler for '{event}'")
