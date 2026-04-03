from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from naru_agent.tools.base import BaseTool


@dataclass
class SkillContext:
    """Context passed to each skill during execution."""

    message: str
    user_id: str | None = None
    session_id: str | None = None
    memory_context: str = ""
    knowledge_store: Any = None  # BaseKnowledgeStore (avoid circular import)

    def get_knowledge(self, query: str, top_k: int = 3) -> str:
        if not self.knowledge_store:
            return ""
        results = self.knowledge_store.search(query, top_k=top_k)
        return "\n".join(r.text for r in results)


@dataclass
class SkillResult:
    """Result returned by a skill execution."""

    prompt_injection: str = ""
    extra_tools: list[BaseTool] = field(default_factory=list)
    override_system_prompt: str | None = None
    skill_name: str = ""
    skipped: bool = False


class BaseSkill(ABC):
    """Base class for all skills."""

    name: str
    description: str
    triggers: list[str]
    priority: int
    always_active: bool
    trigger_conditions: list[str]
    exclusion_conditions: list[str]

    def __init__(
        self,
        name: str = "",
        description: str = "",
        triggers: list[str] | None = None,
        priority: int = 0,
        always_active: bool = False,
        trigger_conditions: list[str] | None = None,
        exclusion_conditions: list[str] | None = None,
    ):
        self.name = name
        self.description = description
        self.triggers = triggers or []
        self.priority = priority
        self.always_active = always_active
        self.trigger_conditions = trigger_conditions or []
        self.exclusion_conditions = exclusion_conditions or []

    @abstractmethod
    def run(self, message: str, context: SkillContext) -> SkillResult:
        ...


class FunctionSkill(BaseSkill):
    """A skill created from a plain function."""

    def __init__(
        self,
        func: Callable,
        name: str | None = None,
        description: str = "",
        triggers: list[str] | None = None,
        priority: int = 0,
        always_active: bool = False,
        trigger_conditions: list[str] | None = None,
        exclusion_conditions: list[str] | None = None,
    ):
        super().__init__(
            name=name or func.__name__,
            description=description or func.__doc__ or "",
            triggers=triggers,
            priority=priority,
            always_active=always_active,
            trigger_conditions=trigger_conditions,
            exclusion_conditions=exclusion_conditions,
        )
        self._func = func

    def run(self, message: str, context: SkillContext) -> SkillResult:
        result = self._func(message, context)
        if isinstance(result, SkillResult):
            if not result.skill_name:
                result.skill_name = self.name
            return result
        # str or other — wrap in SkillResult
        return SkillResult(prompt_injection=str(result) if result else "", skill_name=self.name)


def skill(
    name: str | None = None,
    description: str = "",
    triggers: list[str] | None = None,
    priority: int = 0,
    always_active: bool = False,
    trigger_conditions: list[str] | None = None,
    exclusion_conditions: list[str] | None = None,
) -> Callable:
    """Decorator to turn a function into a Skill.

    Usage::

        @skill(name="greeter", triggers=["hello", "hi"], description="Greeting skill")
        def greet(message: str, context: SkillContext) -> str:
            return "Please respond warmly."
    """

    def decorator(func: Callable) -> FunctionSkill:
        return FunctionSkill(
            func=func,
            name=name or func.__name__,
            description=description,
            triggers=triggers,
            priority=priority,
            always_active=always_active,
            trigger_conditions=trigger_conditions,
            exclusion_conditions=exclusion_conditions,
        )

    return decorator
