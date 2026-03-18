"""AgentFanout — parallel fan-out to multiple agents with result merging."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from naru_agent.agent import NaruResult
from naru_agent.orchestration.orchestrator import AgentChatDelegate


class AgentFanout:
    """Parallel fan-out — send the same message to multiple agents, merge results."""

    def __init__(
        self,
        agents: list[AgentChatDelegate],
        *,
        merge: Callable[[list[NaruResult]], NaruResult] | None = None,
        max_workers: int | None = None,
        name: str = "fanout",
    ) -> None:
        if not agents:
            raise ValueError("Fan-out must have at least one agent")
        self._agents = agents
        self._merge = merge or self._default_merge
        self._max_workers = max_workers or len(agents)
        self.name = name

    def chat(
        self,
        message: str,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> NaruResult:
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {
                pool.submit(a.chat, message, user_id, session_id): i
                for i, a in enumerate(self._agents)
            }
            results: list[tuple[int, NaruResult]] = []
            for future in as_completed(futures):
                idx = futures[future]
                results.append((idx, future.result()))

        # Preserve original order
        results.sort(key=lambda x: x[0])
        return self._merge([r for _, r in results])

    @staticmethod
    def _default_merge(results: list[NaruResult]) -> NaruResult:
        """Default merge: concatenate content with separator."""
        contents = [r.content for r in results if r.content]
        return NaruResult(content="\n\n---\n\n".join(contents))
