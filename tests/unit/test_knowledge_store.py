"""Tests for knowledge store abstractions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from naru_agent.knowledge.base import BaseKnowledgeStore, KnowledgeResult
from naru_agent.knowledge.chroma_store import ChromaKnowledgeStore


class TestKnowledgeResult:
    def test_defaults(self):
        r = KnowledgeResult(text="hello")
        assert r.text == "hello"
        assert r.score == 0.0
        assert r.metadata == {}

    def test_custom(self):
        r = KnowledgeResult(text="x", score=0.9, metadata={"k": "v"})
        assert r.score == 0.9
        assert r.metadata["k"] == "v"


class TestBaseKnowledgeStore:
    def test_format_context_filters_low_scores(self):
        class DummyStore(BaseKnowledgeStore):
            def search(self, query, top_k=3):
                return []

        store = DummyStore()
        results = [
            KnowledgeResult(text="high", score=0.8),
            KnowledgeResult(text="low", score=0.1),
            KnowledgeResult(text="mid", score=0.5),
        ]
        ctx = store.format_context(results, min_score=0.3)
        assert "high" in ctx
        assert "mid" in ctx
        assert "low" not in ctx

    def test_format_context_empty_when_all_low(self):
        class DummyStore(BaseKnowledgeStore):
            def search(self, query, top_k=3):
                return []

        store = DummyStore()
        results = [KnowledgeResult(text="x", score=0.1)]
        assert store.format_context(results, min_score=0.5) == ""


class TestChromaKnowledgeStoreSearch:
    def test_search_empty_collection(self):
        mock_embed = MagicMock(return_value=[[0.1, 0.2]])
        with patch("chromadb.PersistentClient") as mock_client_cls:
            mock_collection = MagicMock()
            mock_collection.count.return_value = 0
            mock_client_cls.return_value.get_or_create_collection.return_value = mock_collection

            store = ChromaKnowledgeStore(
                embed_fn=mock_embed,
                persist_dir="/tmp/test_kb",
            )
            results = store.search("test")
            assert results == []

    def test_search_returns_results(self):
        mock_embed = MagicMock(return_value=[[0.1, 0.2]])
        with patch("chromadb.PersistentClient") as mock_client_cls:
            mock_collection = MagicMock()
            mock_collection.count.return_value = 2
            mock_collection.query.return_value = {
                "documents": [["doc1", "doc2"]],
                "metadatas": [[{"source": "a"}, {"source": "b"}]],
                "distances": [[0.1, 0.5]],
            }
            mock_client_cls.return_value.get_or_create_collection.return_value = mock_collection

            store = ChromaKnowledgeStore(
                embed_fn=mock_embed,
                persist_dir="/tmp/test_kb",
            )
            results = store.search("query", top_k=2)
            assert len(results) == 2
            assert results[0].text == "doc1"
            assert results[0].score == 0.9  # 1 - 0.1
            assert results[1].score == 0.5  # 1 - 0.5


class TestParseMarkdown:
    def test_parse_splits_by_h2(self, tmp_path: Path):
        md = tmp_path / "test.md"
        md.write_text(
            "# Title\n\n"
            "## Section One\n"
            "This is section one content that is long enough to pass the min length check.\n\n"
            "## Section Two\n"
            "Another section with enough content to pass the minimum length threshold.\n",
            encoding="utf-8",
        )
        chunks = ChromaKnowledgeStore._parse_markdown(md)
        assert len(chunks) == 2
        assert chunks[0]["id"] == "test:Section One"
        assert "Section One" in chunks[0]["text"]
        assert chunks[1]["id"] == "test:Section Two"

    def test_parse_skips_short_sections(self, tmp_path: Path):
        md = tmp_path / "short.md"
        md.write_text("## Short\nToo short.\n", encoding="utf-8")
        chunks = ChromaKnowledgeStore._parse_markdown(md)
        assert len(chunks) == 0

    def test_parse_with_custom_id_prefix(self, tmp_path: Path):
        md = tmp_path / "file.md"
        md.write_text(
            "## Topic\n"
            "Enough content here to pass the thirty character minimum length.\n",
            encoding="utf-8",
        )
        chunks = ChromaKnowledgeStore._parse_markdown(md, id_prefix="subdir/file")
        assert chunks[0]["id"] == "subdir/file:Topic"
        assert chunks[0]["metadata"]["source"] == "subdir/file"


class TestIngestMarkdownDir:
    def test_ingest_no_files(self, tmp_path: Path):
        mock_embed = MagicMock(return_value=[[0.1]])
        with patch("chromadb.PersistentClient") as mock_client_cls:
            mock_collection = MagicMock()
            mock_client_cls.return_value.get_or_create_collection.return_value = mock_collection

            store = ChromaKnowledgeStore(embed_fn=mock_embed, persist_dir="/tmp/x")
            count = store.ingest_markdown_dir(tmp_path)
            assert count == 0

    def test_ingest_adds_chunks(self, tmp_path: Path):
        md = tmp_path / "doc.md"
        md.write_text(
            "## Hello\n"
            "This is enough content to pass the thirty character minimum length filter.\n",
            encoding="utf-8",
        )

        mock_embed = MagicMock(return_value=[[0.1, 0.2]])
        with patch("chromadb.PersistentClient") as mock_client_cls:
            mock_collection = MagicMock()
            mock_collection.get.return_value = {"ids": []}
            mock_collection.count.return_value = 1
            mock_client_cls.return_value.get_or_create_collection.return_value = mock_collection

            store = ChromaKnowledgeStore(embed_fn=mock_embed, persist_dir="/tmp/x")
            count = store.ingest_markdown_dir(tmp_path)
            assert count == 1
            mock_collection.add.assert_called_once()
