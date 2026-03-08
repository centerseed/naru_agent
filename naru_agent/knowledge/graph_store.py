"""NetworkX-based knowledge graph store implementing BaseKnowledgeStore."""

from __future__ import annotations

import logging
import pickle
from collections import deque
from pathlib import Path

import networkx as nx

from naru_agent.knowledge.base import BaseKnowledgeStore, KnowledgeResult
from naru_agent.knowledge.graph_extractor import Entity, GraphExtractor, Relation

logger = logging.getLogger(__name__)

_HOP_SCORES = {0: 1.0, 1: 0.7, 2: 0.4}


class GraphKnowledgeStore(BaseKnowledgeStore):
    """Lightweight knowledge graph backed by NetworkX.

    Args:
        extractor: GraphExtractor for LLM-based entity/relation extraction.
        persist_path: File path for pickle persistence.
    """

    def __init__(
        self,
        extractor: GraphExtractor,
        persist_path: str = "./knowledge_graph.pkl",
    ) -> None:
        self._extractor = extractor
        self._persist_path = Path(persist_path)
        self._graph = nx.DiGraph()

    @property
    def graph(self) -> nx.DiGraph:
        """Direct access to the underlying graph for advanced users."""
        return self._graph

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest_text(self, text: str, metadata: dict | None = None) -> int:
        """Extract entities/relations from text and add to graph. Returns count of new relations."""
        entities, relations = self._extractor.extract(text)
        return self._merge(entities, relations, metadata)

    def ingest_texts(self, texts: list[str]) -> int:
        """Ingest multiple texts. Returns total new relations added."""
        total = 0
        for text in texts:
            total += self.ingest_text(text)
        return total

    def ingest_markdown_dir(
        self,
        directory: str | Path,
        force: bool = False,
    ) -> int:
        """Ingest all markdown files from a directory. Returns new relations added."""
        directory = Path(directory)
        if force:
            self._graph.clear()

        md_files = sorted(directory.glob("*.md"))
        if not md_files:
            logger.warning("No markdown files found in %s", directory)
            return 0

        total = 0
        for md_file in md_files:
            content = md_file.read_text(encoding="utf-8")
            # Split by ## headers for better extraction quality on large files
            sections = self._split_sections(content)
            for section in sections:
                total += self.ingest_text(
                    section,
                    metadata={"source": str(md_file.name)},
                )
        return total

    @staticmethod
    def _split_sections(content: str) -> list[str]:
        """Split markdown by ## headers. Returns full content if no headers found."""
        sections: list[str] = []
        current_lines: list[str] = []
        for line in content.split("\n"):
            if line.startswith("## "):
                if current_lines:
                    text = "\n".join(current_lines).strip()
                    if text:
                        sections.append(text)
                current_lines = [line]
            else:
                current_lines.append(line)
        if current_lines:
            text = "\n".join(current_lines).strip()
            if text:
                sections.append(text)
        return sections if sections else [content]

    def _merge(
        self,
        entities: list[Entity],
        relations: list[Relation],
        metadata: dict | None = None,
    ) -> int:
        """Merge entities and relations into the graph, deduplicating by name."""
        for e in entities:
            if self._graph.has_node(e.name):
                existing = self._graph.nodes[e.name]
                if e.description and e.description not in existing.get("description", ""):
                    existing["description"] = (
                        existing.get("description", "") + " " + e.description
                    ).strip()
            else:
                self._graph.add_node(
                    e.name,
                    entity_type=e.entity_type,
                    description=e.description,
                    **(metadata or {}),
                )

        added = 0
        for r in relations:
            if not self._graph.has_edge(r.source, r.target):
                self._graph.add_edge(
                    r.source,
                    r.target,
                    relation_type=r.relation_type,
                    description=r.description,
                )
                added += 1
            else:
                edge = self._graph.edges[r.source, r.target]
                if r.description and r.description not in edge.get("description", ""):
                    edge["description"] = (
                        edge.get("description", "") + " " + r.description
                    ).strip()
        return added

    # ------------------------------------------------------------------
    # Search (BaseKnowledgeStore interface)
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = 3) -> list[KnowledgeResult]:
        """Search the knowledge graph by extracting query entities and expanding via BFS."""
        if self._graph.number_of_nodes() == 0:
            return []

        query_entities, _ = self._extractor.extract(query)
        query_names = [e.name for e in query_entities]

        # Match nodes: exact match first, then substring fallback
        matched_set: set[str] = set()
        all_nodes = list(self._graph.nodes)
        for name in query_names:
            if name in self._graph:
                matched_set.add(name)
            else:
                for node in all_nodes:
                    if name in node or node in name:
                        matched_set.add(node)

        if not matched_set:
            # Last resort: substring match against all query text
            query_lower = query.lower()
            for node in all_nodes:
                if node in query_lower or any(
                    w in node for w in query_lower.split() if len(w) > 2
                ):
                    matched_set.add(node)

        if not matched_set:
            return []

        # BFS expand up to 2 hops, collect unique (edge_text, score)
        seen_texts: set[str] = set()
        results: list[tuple[str, float]] = []
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque()

        def _add_result(text: str, score: float) -> None:
            if text not in seen_texts:
                seen_texts.add(text)
                results.append((text, score))

        for node in matched_set:
            queue.append((node, 0))
            visited.add(node)
            node_data = self._graph.nodes[node]
            desc = node_data.get("description", "")
            if desc:
                _add_result(
                    f"[{node_data.get('entity_type', 'entity')}] {node}: {desc}", 1.0
                )

        while queue:
            current, hop = queue.popleft()
            if hop >= 2:
                continue

            next_hop = hop + 1
            score = _HOP_SCORES.get(next_hop, 0.3)

            # Collect both outgoing and incoming edges
            edges = [
                (current, n, d)
                for _, n, d in self._graph.edges(current, data=True)
            ] + [
                (p, current, d)
                for p, _, d in self._graph.in_edges(current, data=True)
            ]

            for src, dst, edge_data in edges:
                rel = edge_data.get("relation_type", "related_to")
                desc = edge_data.get("description", "")
                text = f"{src} -[{rel}]-> {dst}"
                if desc:
                    text += f": {desc}"
                _add_result(text, score)

                other = dst if src == current else src
                if other not in visited:
                    visited.add(other)
                    queue.append((other, next_hop))

        results.sort(key=lambda x: x[1], reverse=True)

        return [
            KnowledgeResult(text=text, score=score, metadata={"source": "knowledge_graph"})
            for text, score in results[:top_k]
        ]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist graph to disk via pickle."""
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._persist_path, "wb") as f:
            pickle.dump(self._graph, f)
        logger.info("Knowledge graph saved to %s (%d nodes, %d edges)",
                     self._persist_path, self._graph.number_of_nodes(),
                     self._graph.number_of_edges())

    def load(self) -> None:
        """Load graph from disk."""
        if not self._persist_path.exists():
            logger.warning("No graph file at %s, starting empty.", self._persist_path)
            return
        with open(self._persist_path, "rb") as f:
            self._graph = pickle.load(f)
        logger.info("Knowledge graph loaded: %d nodes, %d edges",
                     self._graph.number_of_nodes(), self._graph.number_of_edges())
