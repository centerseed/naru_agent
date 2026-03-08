from __future__ import annotations

import hashlib
import json
import logging
import threading
from abc import ABC, abstractmethod
from typing import Any, Callable

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


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


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
            score = _cosine_similarity(query_emb, skill_embeddings[s.name])
            if score >= self.similarity_threshold:
                scored.append((s, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        selected = [s for s, _ in scored[: self.top_k]]
        return always + selected
