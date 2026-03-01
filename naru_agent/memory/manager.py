from __future__ import annotations

import hashlib
import logging
import threading
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from naru_agent.llm.base import BaseLLM
from naru_agent.memory.base import MemoryItem, MemoryStore
from naru_agent.memory.prompts import (
    FACT_EXTRACTION_PROMPT,
    MEMORY_RECONCILIATION_PROMPT,
)

logger = logging.getLogger(__name__)


class ExtractedFacts(BaseModel):
    facts: list[str]


class ReconciliationAction(BaseModel):
    fact: str
    action: str  # ADD, UPDATE, DELETE, NONE
    target_id: str | None = None
    updated_text: str | None = None


class ReconciliationResult(BaseModel):
    actions: list[ReconciliationAction]


class MemoryManager:
    """mem0-inspired memory manager with LLM-driven fact extraction and reconciliation.

    Usage:
        manager = MemoryManager(llm=my_llm, store=my_store, embed_fn=my_embed)
        manager.add("user_123", messages)
        results = manager.search("user_123", "what does the user prefer?")
    """

    def __init__(
        self,
        llm: BaseLLM,
        store: MemoryStore,
        embed_fn: Any,  # Callable[[str], list[float]]
        reconciliation_top_k: int = 3,
    ):
        self.llm = llm
        self.store = store
        self.embed_fn = embed_fn
        self._top_k = reconciliation_top_k
        self._seen_hashes: set[str] = set()
        self._seen_hashes_lock = threading.Lock()

    def add(self, user_id: str, messages: list[dict[str, str]]) -> list[dict]:
        """Extract facts from messages and reconcile with existing memories."""
        conversation = self._format_messages(messages)
        content_hash = hashlib.md5(conversation.encode()).hexdigest()

        with self._seen_hashes_lock:
            if content_hash in self._seen_hashes:
                return []
            self._seen_hashes.add(content_hash)

        # Step 1: Extract facts via LLM
        facts = self._extract_facts(conversation)
        if not facts:
            return []

        # Step 2: For each fact, find similar existing memories
        existing = []
        for fact in facts:
            embedding = self.embed_fn(fact)
            similar = self.store.search(user_id, embedding, top_k=self._top_k)
            for item in similar:
                if item.id not in [e["id"] for e in existing]:
                    existing.append({"id": item.id, "content": item.content})

        # Step 3: Reconcile via LLM
        actions = self._reconcile(facts, existing)

        # Step 4: Execute actions
        results = []
        for action in actions:
            if action.action == "ADD":
                item = MemoryItem(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    content=action.fact,
                )
                embedding = self.embed_fn(action.fact)
                self.store.add(item, embedding)
                results.append({"event": "ADD", "memory": action.fact})

            elif action.action == "UPDATE" and action.target_id is not None:
                # Map integer ID back to real UUID
                real_id = self._resolve_id(action.target_id, existing)
                if real_id:
                    text = action.updated_text or action.fact
                    embedding = self.embed_fn(text)
                    self.store.update(real_id, text, embedding)
                    results.append({"event": "UPDATE", "memory": text})

            elif action.action == "DELETE" and action.target_id is not None:
                real_id = self._resolve_id(action.target_id, existing)
                if real_id:
                    self.store.delete(real_id)
                    results.append({"event": "DELETE", "id": real_id})

        return results

    def search(self, user_id: str, query: str, top_k: int = 5) -> list[MemoryItem]:
        """Search memories by semantic similarity."""
        embedding = self.embed_fn(query)
        return self.store.search(user_id, embedding, top_k=top_k)

    def get_context_string(self, user_id: str, query: str, top_k: int = 5) -> str:
        """Return a pre-formatted context string for prompt injection."""
        memories = self.search(user_id, query, top_k)
        if not memories:
            return ""
        lines = [f"- {m.content}" for m in memories]
        return "\n".join(lines)

    def get_all(self, user_id: str) -> list[MemoryItem]:
        return self.store.get_all(user_id)

    def _extract_facts(self, conversation: str) -> list[str]:
        prompt = FACT_EXTRACTION_PROMPT.format(conversation=conversation)
        messages = [{"role": "user", "content": prompt}]
        try:
            result = self.llm.chat_structured(
                messages, response_schema=ExtractedFacts, temperature=0.0
            )
            return result.facts
        except Exception:
            logger.exception("Failed to extract facts")
            return []

    def _reconcile(
        self, new_facts: list[str], existing: list[dict]
    ) -> list[ReconciliationAction]:
        if not existing:
            return [
                ReconciliationAction(fact=f, action="ADD") for f in new_facts
            ]

        # Map UUIDs to integers to prevent LLM hallucination
        id_map = {str(i): e["id"] for i, e in enumerate(existing)}
        existing_text = "\n".join(
            f"[{i}] {e['content']}" for i, e in enumerate(existing)
        )
        new_text = "\n".join(f"- {f}" for f in new_facts)

        prompt = MEMORY_RECONCILIATION_PROMPT.format(
            existing_memories=existing_text, new_facts=new_text
        )
        messages = [{"role": "user", "content": prompt}]
        try:
            result = self.llm.chat_structured(
                messages, response_schema=ReconciliationResult, temperature=0.0
            )
            return result.actions
        except Exception:
            logger.exception("Failed to reconcile memories, adding all as new")
            return [
                ReconciliationAction(fact=f, action="ADD") for f in new_facts
            ]

    @staticmethod
    def _resolve_id(target_id: str, existing: list[dict]) -> str | None:
        try:
            idx = int(target_id)
            if 0 <= idx < len(existing):
                return existing[idx]["id"]
        except (ValueError, IndexError):
            pass
        return None

    @staticmethod
    def _format_messages(messages: list[dict[str, str]]) -> str:
        lines = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            lines.append(f"{role}: {content}")
        return "\n".join(lines)
