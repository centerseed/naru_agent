from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from abc import ABC, abstractmethod
from typing import Any, Callable

from naru_agent._math import cosine_similarity
from naru_agent.skills.base import BaseSkill

logger = logging.getLogger(__name__)


class BaseSkillSelector(ABC):
    """Base class for skill selectors."""

    @abstractmethod
    def select(self, skills: list[BaseSkill], message: str) -> list[BaseSkill]:
        ...


class KeywordSkillSelector(BaseSkillSelector):
    """Select skills by case-insensitive keyword matching on triggers."""

    def select(self, skills: list[BaseSkill], message: str) -> list[BaseSkill]:
        msg_lower = message.lower()
        matched: list[BaseSkill] = []
        for s in skills:
            if s.always_active:
                matched.append(s)
                continue
            for trigger in s.triggers:
                if trigger.lower() in msg_lower:
                    matched.append(s)
                    break
        return matched


def _skill_to_text(s: BaseSkill) -> str:
    parts = [s.name, s.description]
    if s.triggers:
        parts.append(" ".join(s.triggers))
    return " | ".join(parts)


def _skills_cache_key(skills: list[BaseSkill]) -> str:
    h = hashlib.md5(usedforsecurity=False)
    for s in sorted(skills, key=lambda s: s.name):
        h.update(s.name.encode())
        h.update(s.description.encode())
        for t in s.triggers:
            h.update(t.encode())
    return h.hexdigest()


class EmbeddingSkillSelector(BaseSkillSelector):
    """Select skills by embedding similarity."""

    def __init__(
        self,
        embed_fn: Callable[[list[str]], list[list[float]]],
        top_k: int = 2,
        similarity_threshold: float = 0.45,
    ):
        self._embed_fn = embed_fn
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold
        self._cache: dict[str, dict[str, list[float]]] = {}
        self._cache_lock = threading.Lock()

    def _ensure_skill_embeddings(self, skills: list[BaseSkill]) -> dict[str, list[float]]:
        cache_key = _skills_cache_key(skills)
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached
            texts = [_skill_to_text(s) for s in skills]
            embeddings = self._embed_fn(texts)
            result = {s.name: emb for s, emb in zip(skills, embeddings)}
            self._cache[cache_key] = result
            return result

    def select(self, skills: list[BaseSkill], message: str) -> list[BaseSkill]:
        # Always include always_active skills
        always = [s for s in skills if s.always_active]
        candidates = [s for s in skills if not s.always_active]

        if not candidates:
            return always

        skill_embeddings = self._ensure_skill_embeddings(candidates)
        query_emb = self._embed_fn([message])[0]

        scored = []
        for s in candidates:
            score = cosine_similarity(query_emb, skill_embeddings[s.name])
            if score >= self.similarity_threshold:
                scored.append((s, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        selected = [s for s, _ in scored[: self.top_k]]
        return always + selected


class LLMSkillSelector(BaseSkillSelector):
    """Select skills using an LLM for intent-based routing.

    The selector sends a structured prompt to an LLM describing each skill's
    trigger conditions and exclusion conditions, then parses the response to
    determine which skills should be activated.

    Args:
        chat_fn: A callable that accepts a prompt string and returns the LLM's
            response string. Wrap any LLM client with a lambda.

    Example::

        selector = LLMSkillSelector(
            chat_fn=lambda prompt: my_llm_client.chat(prompt)
        )
    """

    def __init__(self, chat_fn: Callable[[str], str]):
        self._chat_fn = chat_fn

    def select(self, skills: list[BaseSkill], message: str) -> list[BaseSkill]:
        always = [s for s in skills if s.always_active]
        candidates = [s for s in skills if not s.always_active]

        if not candidates:
            return always

        prompt = self._build_prompt(candidates, message)
        response = self._chat_fn(prompt)
        selected_names = self._parse_response(response)

        name_set = set(selected_names)
        selected = [s for s in candidates if s.name in name_set]
        return always + selected

    def _build_prompt(self, candidates: list[BaseSkill], message: str) -> str:
        lines = [
            "You are a skill router. Given a user message, decide which skills should be activated.",
            "",
            "For each skill below, I provide:",
            "- name: the skill identifier",
            "- trigger_conditions: when this skill SHOULD be activated",
            "- exclusion_conditions: when this skill should NOT be activated",
            "- triggers: keyword hints (fallback if no conditions defined)",
            "",
            "Skills:",
        ]

        for s in candidates:
            lines.append("---")
            lines.append(f"name: {s.name}")
            if s.trigger_conditions:
                lines.append("trigger_conditions:")
                for cond in s.trigger_conditions:
                    lines.append(f'  - "{cond}"')
            if s.exclusion_conditions:
                lines.append("exclusion_conditions:")
                for cond in s.exclusion_conditions:
                    lines.append(f'  - "{cond}"')
            if s.triggers:
                triggers_str = json.dumps(s.triggers, ensure_ascii=False)
                lines.append(f"triggers: {triggers_str}")

        lines.extend([
            "---",
            "",
            f'User message: "{message}"',
            "",
            "Respond with ONLY a JSON array of skill names that should be activated.",
            "If no skills match, respond with [].",
            'Example: ["calendar", "reminder"]',
        ])

        return "\n".join(lines)

    def _parse_response(self, response: str) -> list[str]:
        response = response.strip()

        # Try direct JSON parse
        try:
            result = json.loads(response)
            if isinstance(result, list):
                return [str(item) for item in result]
        except (json.JSONDecodeError, ValueError):
            pass

        # Regex fallback: find a JSON array pattern
        array_match = re.search(r"\[([^\]]*)\]", response)
        if array_match:
            try:
                result = json.loads(array_match.group(0))
                if isinstance(result, list):
                    return [str(item) for item in result]
            except (json.JSONDecodeError, ValueError):
                pass

        # Last resort: extract all quoted strings
        quoted = re.findall(r'"([^"]+)"', response)
        return quoted
