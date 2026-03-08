import type { BaseKnowledgeStore, KnowledgeResult } from "./base.js";
import { formatKnowledgeContext } from "./base.js";
import { cosineSimilarity } from "../utils/math.js";
import type { EmbedFn } from "../types.js";

interface StoredDoc {
  text: string;
  embedding: number[];
  metadata: Record<string, unknown>;
}

/**
 * In-memory vector knowledge store for development and testing.
 * Uses cosine similarity for search — no external dependencies.
 */
export class InMemoryKnowledgeStore implements BaseKnowledgeStore {
  private docs: StoredDoc[] = [];
  private embedFn: EmbedFn;

  constructor(config: { embedFn: EmbedFn }) {
    this.embedFn = config.embedFn;
  }

  /**
   * Ingest a list of text documents. Computes embeddings in batch.
   */
  async batchIngest(
    texts: string[],
    metadataList?: Array<Record<string, unknown>>,
  ): Promise<void> {
    const embeddings = await this.embedFn(texts);
    for (let i = 0; i < texts.length; i++) {
      this.docs.push({
        text: texts[i],
        embedding: embeddings[i],
        metadata: metadataList?.[i] ?? {},
      });
    }
  }

  /**
   * Ingest a single document.
   */
  async ingest(text: string, metadata?: Record<string, unknown>): Promise<void> {
    await this.batchIngest([text], metadata ? [metadata] : undefined);
  }

  async search(query: string, topK = 3): Promise<KnowledgeResult[]> {
    if (this.docs.length === 0) return [];

    const [queryEmbedding] = await this.embedFn([query]);

    return this.docs
      .map((doc) => ({
        text: doc.text,
        score: cosineSimilarity(queryEmbedding, doc.embedding),
        metadata: doc.metadata,
      }))
      .sort((a, b) => b.score - a.score)
      .slice(0, topK);
  }

  formatContext(results: KnowledgeResult[], minScore = 0.3): string {
    return formatKnowledgeContext(results, minScore);
  }

  get size(): number {
    return this.docs.length;
  }
}
