"""Pending state management — tracks confirmations awaiting user response."""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

ConfirmationDisposition = Literal["confirm", "reject", "override"]

_CONFIRM_PATTERN = re.compile(
    r"^(好|確認|對|yes|y|ok|好的|是|沒問題|sure|confirm)$",
    re.IGNORECASE,
)
_REJECT_PATTERN = re.compile(
    r"^(不要|取消|no|n|不|cancel|否|算了|不行|reject)$",
    re.IGNORECASE,
)


def classify_confirmation_disposition(message: str) -> ConfirmationDisposition:
    """Default implementation to classify a user message's disposition toward a pending confirmation."""
    trimmed = message.strip()
    if _CONFIRM_PATTERN.match(trimmed):
        return "confirm"
    if _REJECT_PATTERN.match(trimmed):
        return "reject"
    return "override"


@dataclass
class PendingState:
    """Represents a pending action awaiting user confirmation."""

    type: str  # noqa: A003
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class BasePendingStateManager(ABC):
    """Abstract base for pending state storage backends."""

    @abstractmethod
    def get_pending(self, session_id: str) -> PendingState | None:
        ...

    @abstractmethod
    def set_pending(self, session_id: str, state: PendingState) -> None:
        ...

    @abstractmethod
    def clear_pending(self, session_id: str) -> None:
        ...


class InMemoryPendingStateManager(BasePendingStateManager):
    """Simple in-memory dict implementation of BasePendingStateManager."""

    def __init__(self) -> None:
        self._store: dict[str, PendingState] = {}

    def get_pending(self, session_id: str) -> PendingState | None:
        return self._store.get(session_id)

    def set_pending(self, session_id: str, state: PendingState) -> None:
        self._store[session_id] = state

    def clear_pending(self, session_id: str) -> None:
        self._store.pop(session_id, None)
