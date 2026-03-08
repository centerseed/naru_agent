from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from naru_agent.skills.base import BaseSkill, SkillContext, SkillResult
from naru_agent.skills.selectors import BaseSkillSelector, KeywordSkillSelector

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Registry that selects and runs skills in parallel."""

    def __init__(
        self,
        skills: list[BaseSkill],
        selector: BaseSkillSelector | None = None,
        max_active_skills: int = 3,
    ):
        self.skills = skills
        self.selector = selector or KeywordSkillSelector()
        self.max_active_skills = max_active_skills

    def select_skills(self, message: str) -> list[BaseSkill]:
        selected = self.selector.select(self.skills, message)
        # Sort by priority descending, take top max_active_skills
        selected.sort(key=lambda s: s.priority, reverse=True)
        return selected[: self.max_active_skills]

    def run_skills(self, message: str, context: SkillContext) -> list[SkillResult]:
        selected = self.select_skills(message)
        if not selected:
            return []

        results: list[SkillResult] = []

        if len(selected) == 1:
            # Skip thread pool overhead for the common single-skill case
            try:
                r = selected[0].run(message, context)
                results.append(r)
            except Exception:
                logger.warning("Skill '%s' failed", selected[0].name, exc_info=True)
        else:
            with ThreadPoolExecutor(max_workers=len(selected)) as pool:
                future_to_skill = {
                    pool.submit(s.run, message, context): s for s in selected
                }
                for future in as_completed(future_to_skill):
                    s = future_to_skill[future]
                    try:
                        r = future.result()
                        results.append(r)
                    except Exception:
                        logger.warning("Skill '%s' failed", s.name, exc_info=True)

        # Sort by priority descending
        skill_priority = {s.name: s.priority for s in selected}
        results.sort(key=lambda r: skill_priority.get(r.skill_name, 0), reverse=True)
        return results
