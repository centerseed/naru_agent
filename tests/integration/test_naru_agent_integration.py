"""Integration tests for NaruAgent with real Agno, RAG, memory, and tools.

Requires GEMINI_API_KEY environment variable.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

from naru_agent.agent import NaruAgent, NaruResult
from naru_agent.intent.base import IntentResult
from naru_agent.intent.llm_classifier import LLMIntentClassifier
from naru_agent.knowledge.base import KnowledgeResult
from naru_agent.knowledge.chroma_store import ChromaKnowledgeStore
from naru_agent.tools.base import tool

# Skip all tests if no API key
pytestmark = pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set",
)

MODEL = os.getenv("CHAT_AGENT_MODEL", "gemini/gemini-2.5-flash-lite")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _make_embed_fn():
    """Create embedding function using litellm."""
    import litellm

    def embed_fn(texts: list[str]) -> list[list[float]]:
        response = litellm.embedding(
            model="gemini/gemini-embedding-001",
            input=texts,
            api_key=os.getenv("GEMINI_API_KEY"),
            dimensions=768,
        )
        return [d["embedding"] for d in response.data]

    return embed_fn


# ---------------------------------------------------------------------------
# Test: Basic chat without tools/RAG
# ---------------------------------------------------------------------------


class TestBasicChat:
    def test_simple_response(self):
        agent = NaruAgent(
            model=MODEL,
            api_key=os.getenv("GEMINI_API_KEY"),
            instructions=["You are a helpful assistant. Reply in one sentence."],
        )
        result = agent.chat("Say hello.")
        assert result.content
        assert not result.blocked
        assert result.usage.get("total", 0) > 0
        assert result.timings["total"] > 0


# ---------------------------------------------------------------------------
# Test: Function calling (tools)
# ---------------------------------------------------------------------------


class TestFunctionCalling:
    def test_tool_is_called(self):
        call_log = []

        @tool(description="Get the current weather for a city")
        def get_weather(city: str) -> str:
            call_log.append(city)
            return f"Weather in {city}: 25°C, sunny"

        agent = NaruAgent(
            model=MODEL,
            api_key=os.getenv("GEMINI_API_KEY"),
            instructions=["You are a weather assistant. Use get_weather to answer weather questions."],
            tools=[get_weather],
            tool_call_limit=3,
        )
        result = agent.chat("What's the weather in Tokyo?")
        assert result.content
        assert len(call_log) > 0
        assert "Tokyo" in call_log[0] or "tokyo" in call_log[0].lower()
        assert len(result.tool_calls) > 0

    def test_multiple_tools(self):
        @tool(description="Add two numbers")
        def add(a: int, b: int) -> str:
            return str(a + b)

        @tool(description="Multiply two numbers")
        def multiply(a: int, b: int) -> str:
            return str(a * b)

        agent = NaruAgent(
            model=MODEL,
            api_key=os.getenv("GEMINI_API_KEY"),
            instructions=["You are a math assistant. Use tools to compute."],
            tools=[add, multiply],
            tool_call_limit=5,
        )
        result = agent.chat("What is 3 + 5?")
        assert result.content
        assert "8" in result.content


# ---------------------------------------------------------------------------
# Test: RAG (ChromaKnowledgeStore)
# ---------------------------------------------------------------------------


class TestRAG:
    def test_knowledge_store_search_and_inject(self, tmp_dir):
        # Create knowledge markdown
        knowledge_dir = Path(tmp_dir) / "knowledge"
        knowledge_dir.mkdir()
        (knowledge_dir / "facts.md").write_text(
            "# Facts\n\n"
            "## Python History\n"
            "Python was created by Guido van Rossum and first released in 1991. "
            "It emphasizes code readability and supports multiple programming paradigms.\n\n"
            "## Java History\n"
            "Java was developed by James Gosling at Sun Microsystems and released in 1995. "
            "It follows the principle of write once, run anywhere.\n",
            encoding="utf-8",
        )

        embed_fn = _make_embed_fn()
        store = ChromaKnowledgeStore(
            embed_fn=embed_fn,
            persist_dir=str(Path(tmp_dir) / "chroma_db"),
            collection_name="test_knowledge",
        )
        count = store.ingest_markdown_dir(knowledge_dir)
        assert count == 2

        # Search
        results = store.search("Who created Python?", top_k=2)
        assert len(results) > 0
        assert results[0].score > 0.3
        assert "Python" in results[0].text or "Guido" in results[0].text

        # Use in NaruAgent
        agent = NaruAgent(
            model=MODEL,
            api_key=os.getenv("GEMINI_API_KEY"),
            instructions=["Answer based on the provided knowledge only."],
            knowledge_store=store,
            knowledge_top_k=2,
        )
        result = agent.chat("Who created Python?")
        assert result.content
        assert "Guido" in result.content or "1991" in result.content


# ---------------------------------------------------------------------------
# Test: Intent Classification
# ---------------------------------------------------------------------------


class TestIntentClassification:
    def test_llm_classifier_real(self):
        classifier = LLMIntentClassifier(
            model=MODEL,
            api_key=os.getenv("GEMINI_API_KEY"),
        )
        # Simple greeting — should not need knowledge or tools
        result = classifier.classify("你好")
        assert isinstance(result, IntentResult)
        assert result.raw in ("NN", "NY", "YN", "YY")  # any valid code

    def test_intent_skips_rag_when_nn(self, tmp_dir):
        """When intent = NN, RAG should not be searched."""
        search_count = []

        class TrackingStore(ChromaKnowledgeStore):
            def search(self, query, top_k=3):
                search_count.append(1)
                return super().search(query, top_k)

        # Build a store (empty is fine — we're testing whether search is called)
        embed_fn = _make_embed_fn()
        store = TrackingStore(
            embed_fn=embed_fn,
            persist_dir=str(Path(tmp_dir) / "chroma_db"),
        )

        # Use a classifier that always returns NN
        from naru_agent.intent.base import BaseIntentClassifier

        class AlwaysNN(BaseIntentClassifier):
            def classify(self, message):
                return IntentResult(needs_knowledge=False, needs_tools=False, raw="NN")

        agent = NaruAgent(
            model=MODEL,
            api_key=os.getenv("GEMINI_API_KEY"),
            instructions=["You are a helpful assistant."],
            knowledge_store=store,
            intent_classifier=AlwaysNN(),
        )
        result = agent.chat("你好")
        assert result.content
        assert len(search_count) == 0  # RAG search should NOT have been called


# ---------------------------------------------------------------------------
# Test: Memory integration
# ---------------------------------------------------------------------------


class TestMemoryIntegration:
    def test_memory_context_injected(self):
        """Test that memory context is injected into instructions."""

        class FakeMemory:
            def get_context_string(self, user_id, query):
                return "User prefers morning runs at 6am."

            def add(self, user_id, messages):
                pass

        agent = NaruAgent(
            model=MODEL,
            api_key=os.getenv("GEMINI_API_KEY"),
            instructions=["You are a running coach. Use memory to personalize."],
            memory=FakeMemory(),
        )
        result = agent.chat(
            "When should I run today?",
            user_id="test_user",
        )
        assert result.content
        # The agent should reference the memory (morning runs)
        # This is a soft check — LLM may or may not mention it explicitly


# ---------------------------------------------------------------------------
# Test: Full pipeline (tools + RAG + intent)
# ---------------------------------------------------------------------------


class TestFullPipeline:
    def test_tools_plus_knowledge(self, tmp_dir):
        """End-to-end: intent=YY → knowledge injected + tools used."""
        call_log = []

        @tool(description="Get user's running statistics for the past N days")
        def get_running_stats(days: int) -> str:
            call_log.append(days)
            return f"Past {days} days: 120km total, avg pace 5:30/km"

        # Set up knowledge
        knowledge_dir = Path(tmp_dir) / "knowledge"
        knowledge_dir.mkdir()
        (knowledge_dir / "training.md").write_text(
            "# Training\n\n"
            "## Marathon Preparation\n"
            "For marathon preparation, weekly mileage should reach 60-80km. "
            "Long runs should reach 30-35km. Increase mileage by no more than 10% per week.\n",
            encoding="utf-8",
        )

        embed_fn = _make_embed_fn()
        store = ChromaKnowledgeStore(
            embed_fn=embed_fn,
            persist_dir=str(Path(tmp_dir) / "chroma_db"),
        )
        store.ingest_markdown_dir(knowledge_dir)

        agent = NaruAgent(
            model=MODEL,
            api_key=os.getenv("GEMINI_API_KEY"),
            instructions=[
                "You are a running coach.",
                "Use tools to check user data before giving advice.",
            ],
            tools=[get_running_stats],
            knowledge_store=store,
            tool_call_limit=5,
        )
        result = agent.chat("Am I ready for a marathon? Check my recent runs.")
        assert result.content
        assert result.usage.get("total", 0) > 0


# ---------------------------------------------------------------------------
# Test: Multi-turn Session
# ---------------------------------------------------------------------------


class TestMultiTurnSession:
    def test_same_session_remembers_context(self):
        """Two turns in the same session — second turn can reference the first."""
        agent = NaruAgent(
            model=MODEL,
            api_key=os.getenv("GEMINI_API_KEY"),
            instructions=["You are a helpful assistant. Keep answers short (1-2 sentences)."],
            add_history_to_context=True,
        )
        sid = "test-session-same"

        r1 = agent.chat("My name is Alice.", user_id="u1", session_id=sid)
        assert r1.content
        assert r1.session_id == sid

        r2 = agent.chat("What is my name?", user_id="u1", session_id=sid)
        assert r2.content
        assert "Alice" in r2.content

    def test_different_sessions_isolated(self):
        """Different session_ids should NOT share history."""
        agent = NaruAgent(
            model=MODEL,
            api_key=os.getenv("GEMINI_API_KEY"),
            instructions=["You are a helpful assistant. Keep answers short (1-2 sentences). If you don't know the user's name, say 'I don't know your name'."],
            add_history_to_context=True,
        )

        r1 = agent.chat(
            "My name is Bob.", user_id="u2", session_id="session-A"
        )
        assert r1.content

        r2 = agent.chat(
            "What is my name?", user_id="u2", session_id="session-B"
        )
        assert r2.content
        # Bob should NOT appear since it's a different session
        assert "Bob" not in r2.content
