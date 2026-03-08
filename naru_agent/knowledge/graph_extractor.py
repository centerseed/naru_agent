"""LLM-driven entity and relation extraction for knowledge graphs."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Entity:
    name: str
    entity_type: str
    description: str


@dataclass
class Relation:
    source: str
    target: str
    relation_type: str
    description: str


_EXTRACTION_PROMPT = """\
Extract all entities and relations from the following text.
Return ONLY valid JSON with this exact structure (no markdown fences):
{{"entities": [{{"name": "...", "entity_type": "...", "description": "..."}}], "relations": [{{"source": "...", "target": "...", "relation_type": "...", "description": "..."}}]}}

Rules:
- entity names should be lowercased and trimmed
- source/target in relations must match an entity name exactly
- entity_type examples: person, concept, symptom, disease, medication, organization, technology
- relation_type examples: causes, treats, is_a, part_of, related_to, uses

Text:
{text}"""


class GraphExtractor:
    """Extract entities and relations from text using an LLM."""

    def __init__(
        self,
        model: str = "gemini/gemini-2.5-flash-lite",
        api_key: str | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key

    def extract(self, text: str) -> tuple[list[Entity], list[Relation]]:
        """Extract entities and relations from text."""
        import litellm

        kwargs: dict = {
            "model": self._model,
            "messages": [{"role": "user", "content": _EXTRACTION_PROMPT.format(text=text)}],
            "response_format": {"type": "json_object"},
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key

        response = litellm.completion(**kwargs)
        raw = response.choices[0].message.content.strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM extraction output: %s", raw[:200])
            return [], []

        entities = [
            Entity(
                name=e["name"].strip().lower(),
                entity_type=e.get("entity_type", "concept"),
                description=e.get("description", ""),
            )
            for e in data.get("entities", [])
            if "name" in e
        ]

        entity_names = {e.name for e in entities}
        relations = [
            Relation(
                source=r["source"].strip().lower(),
                target=r["target"].strip().lower(),
                relation_type=r.get("relation_type", "related_to"),
                description=r.get("description", ""),
            )
            for r in data.get("relations", [])
            if "source" in r
            and "target" in r
            and r["source"].strip().lower() in entity_names
            and r["target"].strip().lower() in entity_names
        ]

        return entities, relations
