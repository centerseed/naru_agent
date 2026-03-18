"""AgentHandoffLoop — follows handoff chains across agents with safety limits."""

from __future__ import annotations

import logging

from naru_agent.agent import NaruResult
from naru_agent.orchestration.orchestrator import AgentChatDelegate

logger = logging.getLogger(__name__)


class AgentHandoffLoop:
    """Orchestrator wrapper that follows handoff chains with safety limits."""

    def __init__(
        self,
        agents: dict[str, AgentChatDelegate],
        *,
        entry: str,
        max_handoffs: int = 5,
        name: str = "handoff_loop",
    ) -> None:
        if not agents:
            raise ValueError("Handoff loop must have at least one agent")
        if entry not in agents:
            raise ValueError(f"Entry agent '{entry}' not found in agents")
        self._agents = agents
        self._entry = entry
        self._max_handoffs = max_handoffs
        self.name = name

    def chat(
        self,
        message: str,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> NaruResult:
        current_agent_name = self._entry
        current_message = message
        visited: list[str] = []
        result: NaruResult | None = None

        for _ in range(self._max_handoffs + 1):
            agent = self._agents.get(current_agent_name)
            if agent is None:
                raise ValueError(f"Unknown agent: {current_agent_name}")

            visited.append(current_agent_name)
            result = agent.chat(current_message, user_id=user_id, session_id=session_id)

            if result.handoff is None:
                return result

            # Follow handoff
            current_agent_name = result.handoff.target
            current_message = result.handoff.message or message

        # Limit reached — return last result
        logger.warning(
            "Handoff limit reached (%d), returning last result. Chain: %s",
            self._max_handoffs,
            " → ".join(visited),
        )
        return result  # type: ignore[return-value]
