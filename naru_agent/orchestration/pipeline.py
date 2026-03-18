"""AgentPipeline — sequential pipeline where A.chat() → B.chat(A.content) → C."""

from __future__ import annotations

from naru_agent.agent import NaruResult
from naru_agent.orchestration.orchestrator import AgentChatDelegate


class AgentPipeline:
    """Sequential pipeline — each stage's output becomes the next stage's input."""

    def __init__(
        self,
        stages: list[AgentChatDelegate],
        *,
        name: str = "pipeline",
    ) -> None:
        if not stages:
            raise ValueError("Pipeline must have at least one stage")
        self._stages = stages
        self.name = name

    def chat(
        self,
        message: str,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> NaruResult:
        current_message = message
        result: NaruResult | None = None
        for stage in self._stages:
            result = stage.chat(current_message, user_id=user_id, session_id=session_id)
            current_message = result.content
        return result  # type: ignore[return-value]
