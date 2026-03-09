"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.InMemoryKnowledgeStore = void 0;
const base_js_1 = require("./base.js");
const math_js_1 = require("../utils/math.js");
/**
 * In-memory vector knowledge store for development and testing.
 * Uses cosine similarity for search — no external dependencies.
 *
 * @deprecated Use {@link ChromaKnowledgeStore} for production workloads.
 */
class InMemoryKnowledgeStore {
    docs = [];
    embedFn;
    constructor(config) {
        this.embedFn = config.embedFn;
    }
    /**
     * Ingest a list of text documents. Computes embeddings in batch.
     */
    async batchIngest(texts, metadataList) {
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
    async ingest(text, metadata) {
        await this.batchIngest([text], metadata ? [metadata] : undefined);
    }
    async search(query, topK = 3) {
        if (this.docs.length === 0)
            return [];
        const [queryEmbedding] = await this.embedFn([query]);
        return this.docs
            .map((doc) => ({
            text: doc.text,
            score: (0, math_js_1.cosineSimilarity)(queryEmbedding, doc.embedding),
            metadata: doc.metadata,
        }))
            .sort((a, b) => b.score - a.score)
            .slice(0, topK);
    }
    formatContext(results, minScore = 0.3) {
        return (0, base_js_1.formatKnowledgeContext)(results, minScore);
    }
    get size() {
        return this.docs.length;
    }
}
exports.InMemoryKnowledgeStore = InMemoryKnowledgeStore;
