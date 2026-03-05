"""Unit tests for ChunkContextualizer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from naru_agent.knowledge.contextualizer import ChunkContextualizer


FULL_DOC = "# ACME 年報\n\n## 營收\n\n2025 年總營收 100 億。\n\n## 成本\n\n成本 60 億。"
CHUNK = "【營收】\n2025 年總營收 100 億。"
CONTEXT_REPLY = "此 chunk 位於 ACME 年報的營收章節，說明 2025 年度總營收數字。"


def _mock_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.choices[0].message.content = content
    return resp


class TestChunkContextualizer:
    def test_contextualize_returns_context_prepended_to_chunk(self):
        with patch("litellm.completion", return_value=_mock_response(CONTEXT_REPLY)) as mock_comp:
            c = ChunkContextualizer(model="gemini/gemini-2.5-flash-lite")
            result = c.contextualize(CHUNK, FULL_DOC)

        assert result == f"{CONTEXT_REPLY}\n{CHUNK}"

    def test_prompt_contains_document_and_chunk(self):
        with patch("litellm.completion", return_value=_mock_response(CONTEXT_REPLY)) as mock_comp:
            c = ChunkContextualizer()
            c.contextualize(CHUNK, FULL_DOC)

        call_kwargs = mock_comp.call_args
        prompt_content = call_kwargs[1]["messages"][0]["content"]
        assert FULL_DOC in prompt_content
        assert CHUNK in prompt_content

    def test_api_key_forwarded_when_provided(self):
        with patch("litellm.completion", return_value=_mock_response(CONTEXT_REPLY)) as mock_comp:
            c = ChunkContextualizer(api_key="sk-test")
            c.contextualize(CHUNK, FULL_DOC)

        assert mock_comp.call_args[1]["api_key"] == "sk-test"

    def test_no_api_key_by_default(self):
        with patch("litellm.completion", return_value=_mock_response(CONTEXT_REPLY)) as mock_comp:
            c = ChunkContextualizer()
            c.contextualize(CHUNK, FULL_DOC)

        assert "api_key" not in mock_comp.call_args[1]

    def test_context_stripped(self):
        with patch("litellm.completion", return_value=_mock_response("  padded  ")):
            c = ChunkContextualizer()
            result = c.contextualize(CHUNK, FULL_DOC)

        assert result.startswith("padded")


class TestIngestMarkdownDirWithContextualizer:
    def test_contextualizer_called_for_each_chunk(self, tmp_path: Path):
        md = tmp_path / "doc.md"
        md.write_text(
            "# Title\n\n## Section A\n\n" + "A" * 50 + "\n\n## Section B\n\n" + "B" * 50,
            encoding="utf-8",
        )

        embed_fn = MagicMock(side_effect=lambda texts: [[0.0] * 3 for _ in texts])

        with patch("chromadb.PersistentClient") as mock_client:
            mock_collection = MagicMock()
            mock_collection.count.return_value = 0
            mock_collection.get.return_value = {"ids": []}
            mock_client.return_value.get_or_create_collection.return_value = mock_collection

            from naru_agent.knowledge.chroma_store import ChromaKnowledgeStore

            store = ChromaKnowledgeStore(embed_fn=embed_fn, persist_dir=str(tmp_path / "db"))

            ctx = MagicMock(spec=ChunkContextualizer)
            ctx.contextualize.side_effect = lambda chunk, doc: f"CTX\n{chunk}"

            store.ingest_markdown_dir(tmp_path, contextualizer=ctx)

        # 2 sections → contextualize called twice
        assert ctx.contextualize.call_count == 2
        # full_doc passed as second arg each time
        full_doc = md.read_text(encoding="utf-8")
        for call in ctx.contextualize.call_args_list:
            assert call[0][1] == full_doc

    def test_no_contextualizer_behaviour_unchanged(self, tmp_path: Path):
        md = tmp_path / "doc.md"
        md.write_text("# T\n\n## S\n\n" + "X" * 50, encoding="utf-8")

        embed_fn = MagicMock(side_effect=lambda texts: [[0.1] * 3 for _ in texts])

        with patch("chromadb.PersistentClient") as mock_client:
            mock_collection = MagicMock()
            mock_collection.count.return_value = 0
            mock_collection.get.return_value = {"ids": []}
            mock_client.return_value.get_or_create_collection.return_value = mock_collection

            from naru_agent.knowledge.chroma_store import ChromaKnowledgeStore

            store = ChromaKnowledgeStore(embed_fn=embed_fn, persist_dir=str(tmp_path / "db"))
            count = store.ingest_markdown_dir(tmp_path)

        assert count == 1


class TestBatchIngest:
    def _make_store(self, tmp_path: Path):
        embed_fn = MagicMock(side_effect=lambda texts: [[0.0] * 3 for _ in texts])
        with patch("chromadb.PersistentClient") as mock_client:
            mock_collection = MagicMock()
            mock_collection.count.return_value = 0
            mock_client.return_value.get_or_create_collection.return_value = mock_collection
            from naru_agent.knowledge.chroma_store import ChromaKnowledgeStore
            store = ChromaKnowledgeStore(embed_fn=embed_fn, persist_dir=str(tmp_path / "db"))
            return store, mock_collection

    def test_batch_ingest_without_contextualizer(self, tmp_path: Path):
        store, col = self._make_store(tmp_path)
        count = store.batch_ingest(["hello", "world"])
        assert count == 2
        col.add.assert_called_once()
        docs = col.add.call_args[1]["documents"]
        assert docs == ["hello", "world"]

    def test_batch_ingest_with_contextualizer(self, tmp_path: Path):
        store, col = self._make_store(tmp_path)
        ctx = MagicMock(spec=ChunkContextualizer)
        ctx.contextualize.side_effect = lambda chunk, doc: f"CTX\n{chunk}"
        count = store.batch_ingest(["hello", "world"], contextualizer=ctx, document_context="DOC")
        assert count == 2
        docs = col.add.call_args[1]["documents"]
        assert docs == ["CTX\nhello", "CTX\nworld"]
        assert ctx.contextualize.call_count == 2
