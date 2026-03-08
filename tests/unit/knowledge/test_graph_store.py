"""Tests for GraphKnowledgeStore and GraphExtractor."""

from __future__ import annotations

import pickle
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import networkx as nx
import pytest

from naru_agent.knowledge.base import BaseKnowledgeStore, KnowledgeResult
from naru_agent.knowledge.graph_extractor import Entity, GraphExtractor, Relation
from naru_agent.knowledge.graph_store import GraphKnowledgeStore


# ------------------------------------------------------------------
# GraphExtractor tests (mocked LLM)
# ------------------------------------------------------------------


class TestGraphExtractor:
    def _mock_response(self, content: str) -> MagicMock:
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = content
        return resp

    @patch("litellm.completion")
    def test_extract_entities_and_relations(self, mock_completion):
        mock_completion.return_value = self._mock_response(
            '{"entities": [{"name": "Aspirin", "entity_type": "medication", "description": "pain reliever"},'
            '{"name": "Headache", "entity_type": "symptom", "description": "head pain"}],'
            '"relations": [{"source": "Aspirin", "target": "Headache", "relation_type": "treats", "description": "reduces pain"}]}'
        )
        extractor = GraphExtractor(model="test-model")
        entities, relations = extractor.extract("Aspirin treats headache")

        assert len(entities) == 2
        assert entities[0].name == "aspirin"
        assert entities[1].name == "headache"
        assert len(relations) == 1
        assert relations[0].relation_type == "treats"

    @patch("litellm.completion")
    def test_extract_invalid_json(self, mock_completion):
        mock_completion.return_value = self._mock_response("not json at all")
        extractor = GraphExtractor()
        entities, relations = extractor.extract("test")
        assert entities == []
        assert relations == []

    @patch("litellm.completion")
    def test_extract_filters_dangling_relations(self, mock_completion):
        mock_completion.return_value = self._mock_response(
            '{"entities": [{"name": "A", "entity_type": "concept", "description": ""}],'
            '"relations": [{"source": "A", "target": "B", "relation_type": "related_to", "description": ""}]}'
        )
        extractor = GraphExtractor()
        entities, relations = extractor.extract("test")
        assert len(entities) == 1
        assert len(relations) == 0  # B not in entities


# ------------------------------------------------------------------
# GraphKnowledgeStore tests (pre-built graph, no LLM needed)
# ------------------------------------------------------------------


def _build_store_with_graph() -> GraphKnowledgeStore:
    """Build a store with a pre-populated graph (no LLM calls)."""
    extractor = MagicMock(spec=GraphExtractor)
    store = GraphKnowledgeStore(extractor=extractor)

    g = store.graph
    g.add_node("headache", entity_type="symptom", description="pain in the head")
    g.add_node("aspirin", entity_type="medication", description="NSAID pain reliever")
    g.add_node("stomach ulcer", entity_type="condition", description="gastric lesion")
    g.add_node("ibuprofen", entity_type="medication", description="another NSAID")

    g.add_edge("aspirin", "headache", relation_type="treats", description="relieves pain")
    g.add_edge("aspirin", "stomach ulcer", relation_type="causes", description="side effect")
    g.add_edge("ibuprofen", "headache", relation_type="treats", description="alternative treatment")

    return store


class TestGraphKnowledgeStoreSearch:
    def test_search_with_matched_entity(self):
        store = _build_store_with_graph()
        # Mock extractor to return "aspirin" as query entity
        store._extractor.extract.return_value = (
            [Entity(name="aspirin", entity_type="medication", description="")],
            [],
        )
        results = store.search("what does aspirin do?", top_k=10)
        assert len(results) > 0
        texts = " ".join(r.text for r in results)
        assert "aspirin" in texts
        assert "headache" in texts

    def test_search_empty_graph(self):
        extractor = MagicMock(spec=GraphExtractor)
        store = GraphKnowledgeStore(extractor=extractor)
        store._extractor.extract.return_value = ([], [])
        results = store.search("anything")
        assert results == []

    def test_search_no_match_fallback(self):
        store = _build_store_with_graph()
        store._extractor.extract.return_value = (
            [Entity(name="unknown_entity_xyz", entity_type="concept", description="")],
            [],
        )
        # Should try substring fallback but find nothing
        results = store.search("unknown_entity_xyz")
        assert results == []

    def test_search_substring_fallback(self):
        store = _build_store_with_graph()
        store._extractor.extract.return_value = (
            [Entity(name="aspir", entity_type="concept", description="")],
            [],
        )
        results = store.search("aspir", top_k=10)
        assert len(results) > 0
        assert any("aspirin" in r.text for r in results)

    def test_search_scores_decrease_with_hops(self):
        store = _build_store_with_graph()
        store._extractor.extract.return_value = (
            [Entity(name="aspirin", entity_type="medication", description="")],
            [],
        )
        results = store.search("aspirin", top_k=20)
        scores = [r.score for r in results]
        # First result (hop 0 node) should have score 1.0
        assert scores[0] == 1.0
        # Later results should have lower scores
        assert min(scores) < 1.0

    def test_top_k_limits_results(self):
        store = _build_store_with_graph()
        store._extractor.extract.return_value = (
            [Entity(name="aspirin", entity_type="medication", description="")],
            [],
        )
        results = store.search("aspirin", top_k=2)
        assert len(results) <= 2


class TestGraphKnowledgeStoreIngest:
    @patch("litellm.completion")
    def test_ingest_text(self, mock_completion):
        mock_completion.return_value = MagicMock()
        mock_completion.return_value.choices = [MagicMock()]
        mock_completion.return_value.choices[0].message.content = (
            '{"entities": [{"name": "Python", "entity_type": "technology", "description": "programming language"}],'
            '"relations": []}'
        )
        extractor = GraphExtractor(model="test")
        store = GraphKnowledgeStore(extractor=extractor)
        added = store.ingest_text("Python is a programming language")
        assert store.graph.number_of_nodes() == 1
        assert store.graph.nodes["python"]["entity_type"] == "technology"

    def test_merge_deduplicates(self):
        extractor = MagicMock(spec=GraphExtractor)
        store = GraphKnowledgeStore(extractor=extractor)

        e1 = [Entity("a", "concept", "first")]
        e2 = [Entity("a", "concept", "second")]
        store._merge(e1, [], None)
        store._merge(e2, [], None)

        assert store.graph.number_of_nodes() == 1
        assert "first" in store.graph.nodes["a"]["description"]
        assert "second" in store.graph.nodes["a"]["description"]


class TestGraphKnowledgeStorePersistence:
    def test_save_load_roundtrip(self):
        store = _build_store_with_graph()
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            path = f.name

        store._persist_path = Path(path)
        store.save()

        store2 = GraphKnowledgeStore(
            extractor=MagicMock(spec=GraphExtractor),
            persist_path=path,
        )
        store2.load()

        assert store2.graph.number_of_nodes() == store.graph.number_of_nodes()
        assert store2.graph.number_of_edges() == store.graph.number_of_edges()
        assert "aspirin" in store2.graph.nodes

        Path(path).unlink()

    def test_load_nonexistent(self):
        store = GraphKnowledgeStore(
            extractor=MagicMock(spec=GraphExtractor),
            persist_path="/tmp/nonexistent_graph_test.pkl",
        )
        store.load()  # should not raise
        assert store.graph.number_of_nodes() == 0


class TestGraphKnowledgeStoreMarkdown:
    def test_ingest_markdown_dir(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text("# Title\n\nAspirin treats headache.\n")

        extractor = MagicMock(spec=GraphExtractor)
        extractor.extract.return_value = (
            [
                Entity("aspirin", "medication", "pain reliever"),
                Entity("headache", "symptom", "head pain"),
            ],
            [Relation("aspirin", "headache", "treats", "relieves pain")],
        )
        store = GraphKnowledgeStore(extractor=extractor, persist_path=str(tmp_path / "g.pkl"))
        added = store.ingest_markdown_dir(tmp_path)
        assert added == 1
        assert store.graph.number_of_nodes() == 2


@pytest.mark.integration
@pytest.mark.skipif(
    not __import__("os").getenv("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set",
)
class TestGraphKnowledgeStoreIntegration:
    """Integration tests requiring actual LLM calls. Run with: pytest -m integration"""

    def test_full_pipeline(self, tmp_path):
        extractor = GraphExtractor()
        store = GraphKnowledgeStore(
            extractor=extractor,
            persist_path=str(tmp_path / "graph.pkl"),
        )
        store.ingest_text(
            "Aspirin is a medication that treats headaches. "
            "However, long-term aspirin use can cause stomach ulcers."
        )
        assert store.graph.number_of_nodes() > 0

        results = store.search("What are the side effects of aspirin?")
        assert len(results) > 0

        store.save()
        store2 = GraphKnowledgeStore(
            extractor=extractor,
            persist_path=str(tmp_path / "graph.pkl"),
        )
        store2.load()
        assert store2.graph.number_of_nodes() == store.graph.number_of_nodes()

    def test_markdown_ingest_and_search(self, tmp_path):
        """Test ingesting markdown files and searching across them."""
        (tmp_path / "medicine.md").write_text(
            "# Medicine Guide\n\n"
            "## Pain Relief\n"
            "Aspirin treats headaches and reduces inflammation.\n"
            "Ibuprofen is an alternative to aspirin for pain relief.\n\n"
            "## Side Effects\n"
            "Long-term aspirin use may cause stomach ulcers and bleeding.\n",
            encoding="utf-8",
        )
        (tmp_path / "nutrition.md").write_text(
            "# Nutrition\n\n"
            "## Vitamins\n"
            "Vitamin C boosts the immune system and prevents scurvy.\n"
            "Vitamin D is essential for calcium absorption.\n",
            encoding="utf-8",
        )

        extractor = GraphExtractor()
        store = GraphKnowledgeStore(
            extractor=extractor,
            persist_path=str(tmp_path / "graph.pkl"),
        )
        store.ingest_markdown_dir(tmp_path)

        assert store.graph.number_of_nodes() >= 4

        # Search should find aspirin-related results
        results = store.search("What treats headaches?", top_k=5)
        assert len(results) > 0
        all_text = " ".join(r.text.lower() for r in results)
        assert "headache" in all_text or "aspirin" in all_text

        # Search should find vitamin-related results
        results = store.search("What does vitamin C do?", top_k=5)
        assert len(results) > 0
        all_text = " ".join(r.text.lower() for r in results)
        assert "vitamin" in all_text or "immune" in all_text

    def test_multi_ingest_deduplication(self, tmp_path):
        """Test that ingesting the same content twice deduplicates entities."""
        extractor = GraphExtractor()
        store = GraphKnowledgeStore(
            extractor=extractor,
            persist_path=str(tmp_path / "graph.pkl"),
        )
        text = "Python is a programming language created by Guido van Rossum."
        store.ingest_text(text)
        nodes_after_first = store.graph.number_of_nodes()

        store.ingest_text(text)
        nodes_after_second = store.graph.number_of_nodes()

        # Should not create duplicate nodes
        assert nodes_after_second == nodes_after_first

    def test_hybrid_store_with_graph(self, tmp_path):
        """Test HybridKnowledgeStore combining graph with a mock vector store."""
        from naru_agent.knowledge.hybrid_store import HybridKnowledgeStore

        extractor = GraphExtractor()
        graph_store = GraphKnowledgeStore(
            extractor=extractor,
            persist_path=str(tmp_path / "graph.pkl"),
        )
        graph_store.ingest_text(
            "Aspirin treats headaches. Aspirin can cause stomach ulcers."
        )

        # Create a simple mock vector store
        mock_vector = MagicMock(spec=BaseKnowledgeStore)
        mock_vector.search.return_value = [
            KnowledgeResult(
                text="Aspirin dosage: 300-900mg every 4-6 hours.",
                score=0.85,
                metadata={"source": "vector"},
            )
        ]

        hybrid = HybridKnowledgeStore(
            stores=[mock_vector, graph_store],
            weights=[1.0, 0.8],
        )
        results = hybrid.search("Tell me about aspirin", top_k=5)

        assert len(results) > 1
        sources = {r.metadata.get("source") for r in results}
        # Should have results from both stores
        assert "vector" in sources
        assert "knowledge_graph" in sources

    def test_agent_with_graph_knowledge(self, tmp_path):
        """Test that NaruAgent can use GraphKnowledgeStore via chat()."""
        from naru_agent.agent import Agent
        from naru_agent.llm import LiteLLMProvider
        from naru_agent.runner import Runner

        extractor = GraphExtractor()
        store = GraphKnowledgeStore(
            extractor=extractor,
            persist_path=str(tmp_path / "graph.pkl"),
        )
        store.ingest_text(
            "Aspirin is a medication that treats headaches. "
            "Long-term aspirin use can cause stomach ulcers. "
            "Ibuprofen is an alternative painkiller."
        )

        llm = LiteLLMProvider(model="gemini/gemini-2.5-flash-lite")
        agent = Agent(
            name="medical_qa",
            role="Medical knowledge assistant",
            llm=llm,
            knowledge_store=store,
        )
        runner = Runner(agent)
        result = runner.run(message="What are the side effects of aspirin?")

        assert result.content
        # The response should reference knowledge from the graph
        content_lower = result.content.lower()
        assert "stomach" in content_lower or "ulcer" in content_lower or "side effect" in content_lower
