"""ChromaDB-backed knowledge store for RAG."""

from __future__ import annotations

import logging
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
            all_chunks.extend(self._parse_markdown(md_file, id_prefix=str(rel_path.with_suffix(""))))

        if not all_chunks:
            return 0

        existing_ids = set(self._collection.get()["ids"]) if not force else set()
        new_chunks = [c for c in all_chunks if c["id"] not in existing_ids]
        if not new_chunks:
            logger.info("All %d chunks already ingested, skipping.", len(all_chunks))
            return 0

        total_added = 0
        for i in range(0, len(new_chunks), batch_size):
            batch = new_chunks[i : i + batch_size]
            texts = [c["text"] for c in batch]
            embeddings = self._embed_fn(texts)
            self._collection.add(
                ids=[c["id"] for c in batch],
                documents=texts,
                embeddings=embeddings,
                metadatas=[c["metadata"] for c in batch],
            )
            total_added += len(batch)

        logger.info(
            "Ingested %d new chunks (total: %d)",
            total_added,
            self._collection.count(),
        )
        return total_added

    @staticmethod
    def _parse_markdown(
        filepath: Path,
        id_prefix: str | None = None,
    ) -> list[dict[str, Any]]:
        """Parse a markdown file into chunks, split by ``## Header``.

        Args:
            filepath: Path to the markdown file.
            id_prefix: Prefix for chunk IDs (defaults to file stem).
                       Use relative path to avoid collisions across directories.
        """
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
