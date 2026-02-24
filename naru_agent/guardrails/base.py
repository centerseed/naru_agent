from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class GuardrailResult(BaseModel):
    passed: bool
    modified_text: str | None = None
    reason: str | None = None


class BaseGuardrail(ABC):
    """Base guardrail interface. Implement check_input and/or check_output."""

    @abstractmethod
    def check_input(self, message: str) -> GuardrailResult:
        ...

    @abstractmethod
    def check_output(self, response: str) -> GuardrailResult:
        ...
