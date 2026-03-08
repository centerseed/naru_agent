import type { BaseKnowledgeStore, KnowledgeResult } from "./base.js";
import { formatKnowledgeContext } from "./base.js";
import type { EmbedFn } from "../types.js";
import { toVectorLiteral } from "../utils/math.js";

/**
 * pgvector-backed knowledge store for vector retrieval.
 */
export class PgVectorKnowledgeStore implements BaseKnowledgeStore {
  private pool: import("pg").Pool;
  private embedFn: EmbedFn;
  private tableName: string;
  private dimensions: number;
  private initialized = false;

  constructor(config: {
    pool: import("pg").Pool;
    embedFn: EmbedFn;
    tableName?: string;
    dimensions?: number;
  }) {
    this.pool = config.pool;
    this.embedFn = config.embedFn;
    this.tableName = config.tableName ?? "naru_knowledge";
    this.dimensions = config.dimensions ?? 1536;
  }

  private async ensureTable(): Promise<void> {
    if (this.initialized) return;
    await this.pool.query(`
      CREATE TABLE IF NOT EXISTS ${this.tableName} (
        id TEXT PRIMARY KEY,
        content TEXT NOT NULL,
        metadata JSONB DEFAULT '{}',
        embedding vector(${this.dimensions}),
        created_at TIMESTAMPTZ DEFAULT NOW()
      )
    `);
    this.initialized = true;
  }

  async search(query: string, topK = 3): Promise<KnowledgeResult[]> {
    await this.ensureTable();
    const [queryEmbedding] = await this.embedFn([query]);
    const result = await this.pool.query(
      `SELECT content, metadata,
              1 - (embedding <=> $1::vector) AS score
       FROM ${this.tableName}
       ORDER BY embedding <=> $1::vector
       LIMIT $2`,
      [toVectorLiteral(queryEmbedding), topK],
    );
    return result.rows.map((r: Record<string, unknown>) => ({
      text: r.content as string,
      score: r.score as number,
      metadata: (r.metadata ?? {}) as Record<string, unknown>,
    }));
  }

  formatContext(results: KnowledgeResult[], minScore = 0.3): string {
    return formatKnowledgeContext(results, minScore);
  }

  async ingest(
    chunks: Array<{ id: string; content: string; metadata?: Record<string, unknown> }>,
    batchSize = 20,
  ): Promise<number> {
    await this.ensureTable();
    let count = 0;
    for (let i = 0; i < chunks.length; i += batchSize) {
      const batch = chunks.slice(i, i + batchSize);
      const embeddings = await this.embedFn(batch.map((c) => c.content));
      await Promise.all(
        batch.map((chunk, j) =>
          this.pool.query(
            `INSERT INTO ${this.tableName} (id, content, metadata, embedding)
             VALUES ($1, $2, $3, $4)
             ON CONFLICT (id) DO UPDATE SET content = $2, metadata = $3, embedding = $4`,
            [
              chunk.id,
              chunk.content,
              JSON.stringify(chunk.metadata ?? {}),
              toVectorLiteral(embeddings[j]),
            ],
          ),
        ),
      );
      count += batch.length;
    }
    return count;
  }
}
