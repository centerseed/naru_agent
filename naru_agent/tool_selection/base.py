from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from naru_agent.tools.base import BaseTool


@dataclass
class ToolSelectionResult:
    selected_tools: list[BaseTool]
    all_tools: list[BaseTool]
    scores: dict[str, float] = field(default_factory=dict)

    @property
    def was_filtered(self) -> bool:
        return len(self.selected_tools) < len(self.all_tools)


class BaseToolSelector(ABC):
    @abstractmethod
    def select_tools(
        self,
        tools: list[BaseTool],
        query: str,
        context: list[dict] | None = None,
        used_tool_names: set[str] | None = None,
    ) -> ToolSelectionResult: ...
