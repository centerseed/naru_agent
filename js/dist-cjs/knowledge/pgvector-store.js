"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.PgVectorKnowledgeStore = void 0;
const base_js_1 = require("./base.js");
const math_js_1 = require("../utils/math.js");
/**
 * pgvector-backed knowledge store for vector retrieval.
 */
class PgVectorKnowledgeStore {
    pool;
    embedFn;
    tableName;
    dimensions;
    initialized = false;
    constructor(config) {
        this.pool = config.pool;
        this.embedFn = config.embedFn;
        this.tableName = config.tableName ?? "naru_knowledge";
        this.dimensions = config.dimensions ?? 1536;
    }
    async ensureTable() {
        if (this.initialized)
            return;
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
    async search(query, topK = 3) {
        await this.ensureTable();
        const [queryEmbedding] = await this.embedFn([query]);
        const result = await this.pool.query(`SELECT content, metadata,
              1 - (embedding <=> $1::vector) AS score
       FROM ${this.tableName}
       ORDER BY embedding <=> $1::vector
       LIMIT $2`, [(0, math_js_1.toVectorLiteral)(queryEmbedding), topK]);
        return result.rows.map((r) => ({
            text: r.content,
            score: r.score,
            metadata: (r.metadata ?? {}),
        }));
    }
    formatContext(results, minScore = 0.3) {
        return (0, base_js_1.formatKnowledgeContext)(results, minScore);
    }
    async ingest(chunks, batchSize = 20) {
        await this.ensureTable();
        let count = 0;
        for (let i = 0; i < chunks.length; i += batchSize) {
            const batch = chunks.slice(i, i + batchSize);
            const embeddings = await this.embedFn(batch.map((c) => c.content));
            await Promise.all(batch.map((chunk, j) => this.pool.query(`INSERT INTO ${this.tableName} (id, content, metadata, embedding)
             VALUES ($1, $2, $3, $4)
             ON CONFLICT (id) DO UPDATE SET content = $2, metadata = $3, embedding = $4`, [
                chunk.id,
                chunk.content,
                JSON.stringify(chunk.metadata ?? {}),
                (0, math_js_1.toVectorLiteral)(embeddings[j]),
            ])));
            count += batch.length;
        }
        return count;
    }
}
exports.PgVectorKnowledgeStore = PgVectorKnowledgeStore;
