"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.PgVectorMemoryStore = void 0;
const math_js_1 = require("../utils/math.js");
/**
 * PostgreSQL + pgvector backed memory store. Requires `pg` as optional dependency.
 */
class PgVectorMemoryStore {
    pool;
    tableName;
    dimensions;
    initialized = false;
    constructor(config) {
        this.pool = config.pool;
        this.tableName = config.tableName ?? "naru_memories";
        this.dimensions = config.dimensions ?? 1536;
    }
    async ensureTable() {
        if (this.initialized)
            return;
        await this.pool.query(`
      CREATE TABLE IF NOT EXISTS ${this.tableName} (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        content TEXT NOT NULL,
        metadata JSONB DEFAULT '{}',
        embedding vector(${this.dimensions}),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
      )
    `);
        await this.pool.query(`
      CREATE INDEX IF NOT EXISTS idx_${this.tableName}_user_id
      ON ${this.tableName}(user_id)
    `);
        this.initialized = true;
    }
    async add(item, embedding) {
        await this.ensureTable();
        await this.pool.query(`INSERT INTO ${this.tableName} (id, user_id, content, metadata, embedding, created_at, updated_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7)
       ON CONFLICT (id) DO UPDATE SET content = $3, metadata = $4, embedding = $5, updated_at = $7`, [
            item.id,
            item.userId,
            item.content,
            JSON.stringify(item.metadata),
            (0, math_js_1.toVectorLiteral)(embedding),
            item.createdAt,
            item.updatedAt,
        ]);
    }
    async search(userId, embedding, topK = 5) {
        await this.ensureTable();
        const result = await this.pool.query(`SELECT id, user_id, content, metadata, created_at, updated_at,
              1 - (embedding <=> $1::vector) AS score
       FROM ${this.tableName}
       WHERE user_id = $2
       ORDER BY embedding <=> $1::vector
       LIMIT $3`, [(0, math_js_1.toVectorLiteral)(embedding), userId, topK]);
        return result.rows.map((r) => ({
            id: r.id,
            userId: r.user_id,
            content: r.content,
            metadata: (r.metadata ?? {}),
            score: r.score,
            createdAt: new Date(r.created_at),
            updatedAt: new Date(r.updated_at),
        }));
    }
    async update(itemId, content, embedding) {
        await this.ensureTable();
        await this.pool.query(`UPDATE ${this.tableName} SET content = $1, embedding = $2, updated_at = NOW() WHERE id = $3`, [content, (0, math_js_1.toVectorLiteral)(embedding), itemId]);
    }
    async delete(itemId) {
        await this.ensureTable();
        await this.pool.query(`DELETE FROM ${this.tableName} WHERE id = $1`, [itemId]);
    }
    async getAll(userId) {
        await this.ensureTable();
        const result = await this.pool.query(`SELECT id, user_id, content, metadata, created_at, updated_at
       FROM ${this.tableName} WHERE user_id = $1 ORDER BY created_at`, [userId]);
        return result.rows.map((r) => ({
            id: r.id,
            userId: r.user_id,
            content: r.content,
            metadata: (r.metadata ?? {}),
            createdAt: new Date(r.created_at),
            updatedAt: new Date(r.updated_at),
        }));
    }
}
exports.PgVectorMemoryStore = PgVectorMemoryStore;
