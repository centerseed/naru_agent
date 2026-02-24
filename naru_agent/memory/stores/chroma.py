from __future__ import annotations

from datetime import datetime

import chromadb

from naru_agent.memory.base import MemoryItem, MemoryStore


class ChromaMemoryStore(MemoryStore):
    """ChromaDB-backed memory store.

    Usage:
        store = ChromaMemoryStore(persist_dir="./memory_db", collection_name="user_memories")
    """

    def __init__(
        self,
        persist_dir: str = "./memory_db",
        collection_name: str = "memories",
    ):
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def add(self, item: MemoryItem, embedding: list[float]) -> None:
        self._collection.add(
            ids=[item.id],
            embeddings=[embedding],
            documents=[item.content],
            metadatas=[{
                "user_id": item.user_id,
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat(),
                **item.metadata,
            }],
        )

    def search(
        self, user_id: str, embedding: list[float], top_k: int = 5
    ) -> list[MemoryItem]:
        results = self._collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            where={"user_id": user_id},
        )
        items = []
        if results["ids"] and results["ids"][0]:
            for i, id_ in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                distance = results["distances"][0][i] if results["distances"] else None
                items.append(MemoryItem(
                    id=id_,
                    user_id=user_id,
                    content=results["documents"][0][i],
                    metadata={k: v for k, v in meta.items() if k not in ("user_id", "created_at", "updated_at")},
                    score=1.0 - distance if distance is not None else None,
                ))
        return items

    def update(self, item_id: str, content: str, embedding: list[float]) -> None:
        existing = self._collection.get(ids=[item_id])
        meta = existing["metadatas"][0] if existing["metadatas"] else {}
        meta["updated_at"] = datetime.utcnow().isoformat()

        self._collection.update(
            ids=[item_id],
            embeddings=[embedding],
            documents=[content],
            metadatas=[meta],
        )

    def delete(self, item_id: str) -> None:
        self._collection.delete(ids=[item_id])

    def get_all(self, user_id: str) -> list[MemoryItem]:
        results = self._collection.get(where={"user_id": user_id})
        items = []
        if results["ids"]:
            for i, id_ in enumerate(results["ids"]):
                meta = results["metadatas"][i] if results["metadatas"] else {}
                items.append(MemoryItem(
                    id=id_,
                    user_id=user_id,
                    content=results["documents"][i],
                    metadata={k: v for k, v in meta.items() if k not in ("user_id", "created_at", "updated_at")},
                ))
        return items
