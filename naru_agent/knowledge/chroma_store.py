"""ChromaDB-backed knowledge store for RAG."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Callable

from naru_agent.knowledge.base import BaseKnowledgeStore, KnowledgeResult

logger = logging.getLogger(__name__)


class ChromaKnowledgeStore(BaseKnowledgeStore):
    """Generic ChromaDB vector store for knowledge retrieval.

    Args:
        embed_fn: A callable that takes a list of strings and returns
                  a list of embedding vectors (list[list[float]]).
        persist_dir: Directory for ChromaDB persistence.
        collection_name: Name of the ChromaDB collection.
    """

    def __init__(
        self,
        embed_fn: Callable[[list[str]], list[list[float]]],
        persist_dir: str = "./knowledge_db",
        collection_name: str = "knowledge",
    ) -> None:
        import chromadb

        self._embed_fn = embed_fn
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def search(self, query: str, top_k: int = 3) -> list[KnowledgeResult]:
        """Search knowledge by semantic similarity."""
        if self._collection.count() == 0:
            return []

        query_embedding = self._embed_fn([query])[0]
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self._collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        items: list[KnowledgeResult] = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            items.append(
                KnowledgeResult(
                    text=doc,
                    score=round(1 - dist, 3),  # cosine distance -> similarity
                    metadata=meta or {},
                )
            )
        return items

    # ------------------------------------------------------------------
    # Ingestion helpers
    # ------------------------------------------------------------------

    def ingest_markdown_dir(
        self,
        directory: str | Path,
        force: bool = False,
        batch_size: int = 20,
        contextualizer: "ChunkContextualizer | None" = None,
    ) -> int:
        """Ingest all markdown files from a directory.

        Splits by ``## Header`` sections. Returns number of chunks added.

        Note:
            Chunk IDs are derived from section headings. If a heading is
            renamed, the old chunk remains in ChromaDB as stale data. Use
            ``force=True`` to rebuild from scratch, or call
            ``_client.delete_collection()`` manually when headings change.
        """
        directory = Path(directory)
        if force:
            self._client.delete_collection(self._collection.name)
            self._collection = self._client.get_or_create_collection(
                name=self._collection.name,
                metadata={"hnsw:space": "cosine"},
            )

        md_files = sorted(directory.glob("*.md"))
        if not md_files:
            logger.warning("No markdown files found in %s", directory)
            return 0

        all_chunks: list[dict[str, Any]] = []
        for md_file in md_files:
            rel_path = md_file.relative_to(directory)
            # Read once and pass to _parse_markdown to avoid a second read.
            full_doc = md_file.read_text(encoding="utf-8")
            chunks = self._parse_markdown(
                md_file,
                id_prefix=str(rel_path.with_suffix("")),
                content=full_doc,
            )
            if contextualizer:
                for c in chunks:
                    c["text"] = contextualizer.contextualize(c["text"], full_doc)
            all_chunks.extend(chunks)

        if not all_chunks:
            return 0

        existing_ids = set(self._collection.get()["ids"]) if not force else set()
        new_chunks = [c for c in all_chunks if c["id"] not in existing_ids]
        if not new_chunks:
            logger.info("All %d chunks already ingested, skipping.", len(all_chunks))
            return 0

        total_added = self._add_batched(
            texts=[c["text"] for c in new_chunks],
            ids=[c["id"] for c in new_chunks],
            metadatas=[c["metadata"] for c in new_chunks],
            batch_size=batch_size,
        )
        logger.info(
            "Ingested %d new chunks (total: %d)",
            total_added,
            self._collection.count(),
        )
        return total_added

    def batch_ingest(
        self,
        texts: list[str],
        metadatas: list[dict] | None = None,
        ids: list[str] | None = None,
        contextualizer: "ChunkContextualizer | None" = None,
        document_context: str = "",
        batch_size: int = 20,
    ) -> int:
        """批次 ingest 任意文字清單。

        Args:
            texts: chunk 文字清單
            metadatas: 對應的 metadata（可選）
            ids: 自訂 chunk ID（可選，預設自動生成 UUID）
            contextualizer: 若提供則為每個 chunk 補充定位上下文
            document_context: 整份文件原文，供 contextualizer 理解 chunk 所處脈絡
            batch_size: 每批 embed 的數量
        """
        if not texts:
            return 0

        if contextualizer and not document_context:
            logger.warning(
                "batch_ingest: contextualizer provided but document_context is empty; "
                "context quality may be degraded."
            )

        if ids is None:
            ids = [str(uuid.uuid4()) for _ in texts]
        if metadatas is None:
            metadatas = [{"_src": "batch_ingest"} for _ in texts]

        final_texts = (
            [contextualizer.contextualize(t, document_context) for t in texts]
            if contextualizer
            else texts
        )

        total_added = self._add_batched(
            texts=final_texts,
            ids=ids,
            metadatas=metadatas,
            batch_size=batch_size,
        )
        logger.info("batch_ingest: added %d chunks", total_added)
        return total_added

    def _add_batched(
        self,
        texts: list[str],
        ids: list[str],
        metadatas: list[dict],
        batch_size: int,
    ) -> int:
        """Embed and add texts to the collection in batches."""
        total_added = 0
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i : i + batch_size]
            embeddings = self._embed_fn(batch_texts)
            self._collection.add(
                ids=ids[i : i + batch_size],
                documents=batch_texts,
                embeddings=embeddings,
                metadatas=metadatas[i : i + batch_size],
            )
            total_added += len(batch_texts)
        return total_added

    @staticmethod
    def _parse_markdown(
        filepath: Path,
        id_prefix: str | None = None,
        content: str | None = None,
    ) -> list[dict[str, Any]]:
        """Parse a markdown file into chunks, split by ``## Header``.

        Args:
            filepath: Path to the markdown file.
            id_prefix: Prefix for chunk IDs (defaults to file stem).
                       Use relative path to avoid collisions across directories.
            content: Pre-read file content. If omitted, the file is read from disk.
        """
        if content is None:
            content = filepath.read_text(encoding="utf-8")
        prefix = id_prefix or filepath.stem

        chunks: list[dict[str, Any]] = []
        current_section: str | None = None
        current_lines: list[str] = []

        for line in content.split("\n"):
            if line.startswith("## "):
                if current_section and current_lines:
                    text = "\n".join(current_lines).strip()
                    if len(text) >= 30:
                        chunks.append({
                            "id": f"{prefix}:{current_section}",
                            "text": f"\u3010{current_section}\u3011\n{text}",
                            "metadata": {
                                "source": prefix,
                                "section": current_section,
                            },
                        })
                current_section = line[3:].strip()
                current_lines = []
            elif line.startswith("# ") and not current_section:
                continue
            else:
                current_lines.append(line)

        # Last section
        if current_section and current_lines:
            text = "\n".join(current_lines).strip()
            if len(text) >= 30:
                chunks.append({
                    "id": f"{prefix}:{current_section}",
                    "text": f"\u3010{current_section}\u3011\n{text}",
                    "metadata": {
                        "source": prefix,
                        "section": current_section,
                    },
                })

        return chunks
