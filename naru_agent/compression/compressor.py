from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from naru_agent.compression.base import BaseSummaryStore, CompressedSummary

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT = """\
You are a conversation summarizer. Summarize the following conversation history \
into a concise summary of at most 300 words. Focus on key facts, decisions, \
user preferences, and important context. Do NOT include greetings or filler.

Conversation:
{conversation}

Summary:"""


class ContextCompressor:
    """Manages context compression for NaruAgent sessions.

    Reads the latest summary synchronously (for injection before LLM call),
    and triggers background compression after each run.
    """

    def __init__(
        self,
        summary_store: BaseSummaryStore,
        summary_model: str = "ollama/gemma:12b",
        summary_api_base: str | None = None,
        keep_last_rounds: int = 5,
        threshold_rounds: int = 5,
    ) -> None:
        self._store = summary_store
        self._model = summary_model
        self._api_base = summary_api_base
        self._keep_last = keep_last_rounds
        self._threshold = threshold_rounds

    def get_summary_sync(self, session_id: str) -> CompressedSummary | None:
        """Synchronously read the latest summary from the store."""
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None:
                # We're inside an async context; run in a separate thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(
                        asyncio.run, self._store.get(session_id)
                    ).result(timeout=5)
            else:
                return asyncio.run(self._store.get(session_id))
        except Exception:
            logger.warning("Failed to read summary for session %s", session_id)
            return None

    def maybe_compress(self, session_id: str, agno_agent: Any) -> None:
        """Check if compression is needed and run it.

        Called from a background thread after agno_agent.run() completes.
        """
        try:
            session = self._get_session(agno_agent, session_id)
            if session is None:
                return

            runs = getattr(session, "runs", None) or []
            total_runs = len(runs)

            if total_runs <= self._threshold:
                return

            compress_through = total_runs - self._keep_last
            if compress_through <= 0:
                return

            # Extract conversation text from runs to compress
            conversation_text = self._extract_conversation(runs[:compress_through])
            if not conversation_text.strip():
                return

            asyncio.run(
                self._compress_and_save(session_id, compress_through, conversation_text)
            )
        except Exception:
            logger.exception("Background compression failed for session %s", session_id)

    async def _compress_and_save(
        self, session_id: str, compress_through: int, conversation_text: str
    ) -> None:
        """Check, generate, and persist a summary in a single event loop run."""
        existing = await self._store.get(session_id)
        if existing and existing.compressed_through_run >= compress_through:
            return

        summary_text = self._call_llm(conversation_text)
        if not summary_text:
            return

        summary = CompressedSummary(
            summary_text=summary_text,
            compressed_through_run=compress_through,
            created_at=time.time(),
            model_used=self._model,
        )
        await self._store.save(session_id, summary)
        logger.info("Compressed %d runs for session %s", compress_through, session_id)

    def _get_session(self, agno_agent: Any, session_id: str) -> Any:
        """Retrieve the Agno session object."""
        try:
            db = getattr(agno_agent, "db", None)
            if db is None:
                return None
            sessions = getattr(db, "sessions", None)
            if sessions is None:
                # Try reading from db
                session = db.read(session_id)
                return session
            return sessions.get(session_id)
        except Exception:
            logger.warning("Could not read session %s from agent db", session_id)
            return None

    def _extract_conversation(self, runs: list[Any]) -> str:
        """Extract human-readable conversation text from Agno runs."""
        parts: list[str] = []
        for run in runs:
            messages = getattr(run, "messages", None) or []
            for msg in messages:
                role = getattr(msg, "role", None)
                content = getattr(msg, "content", None)
                if role in ("user", "assistant") and content:
                    parts.append(f"{role}: {content}")
        return "\n".join(parts)

    def _call_llm(self, conversation_text: str) -> str:
        """Call a cheap LLM to generate the summary."""
        try:
            import litellm  # noqa: F811

            kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": [
                    {
                        "role": "user",
                        "content": _SUMMARY_PROMPT.format(conversation=conversation_text),
                    }
                ],
                "temperature": 0.3,
                "max_tokens": 1024,
            }
            if self._api_base:
                kwargs["api_base"] = self._api_base

            response = litellm.completion(**kwargs)
            return response.choices[0].message.content or ""
        except Exception:
            logger.exception("Summary LLM call failed")
            return ""
