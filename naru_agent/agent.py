from __future__ import annotations

from pydantic import BaseModel, Field

from typing import Any

from naru_agent.llm.base import BaseLLM
from naru_agent.tools.base import BaseTool
from naru_agent.guardrails.base import BaseGuardrail


class Agent(BaseModel):
    """A configurable agent with tools, memory, and guardrails."""

    model_config = {"arbitrary_types_allowed": True}

    name: str
    role: str
    goal: str = ""
    system_prompt: str = ""
    llm: BaseLLM
    tools: list[BaseTool] = Field(default_factory=list)
    memory: Any = None
    guardrails: list[BaseGuardrail] = Field(default_factory=list)
    max_iterations: int = 10
    metadata: dict = Field(default_factory=dict)

    def get_system_message(self, memory_context: str = "") -> str:
        parts = []
        if self.system_prompt:
            parts.append(self.system_prompt)
        else:
            parts.append(f"You are {self.name}, a {self.role}.")
            if self.goal:
                parts.append(f"Your goal: {self.goal}")

        if memory_context:
            parts.append(f"\n## Relevant User Context\n{memory_context}")

        return "\n\n".join(parts)

    def get_tool_schemas(self) -> list[dict]:
        return [t.to_schema() for t in self.tools]

    def get_tool_by_name(self, name: str) -> BaseTool | None:
        for t in self.tools:
            if t.name == name:
                return t
        return None
