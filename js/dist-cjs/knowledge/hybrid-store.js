"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.HybridKnowledgeStore = void 0;
const base_js_1 = require("./base.js");
/**
 * Multi-source knowledge store that merges results from multiple stores
 * with weighted scoring.
 */
class HybridKnowledgeStore {
    stores;
    weights;
    constructor(config) {
        this.stores = config.stores;
        this.weights =
            config.weights ?? config.stores.map(() => 1 / config.stores.length);
    }
    async search(query, topK = 3) {
        const allResults = await Promise.allSettled(this.stores.map((store, i) => store.search(query, topK).then((results) => results.map((r) => ({
            ...r,
            score: r.score * this.weights[i],
        })))));
        const merged = [];
        const seen = new Set();
        for (const result of allResults) {
            if (result.status === "fulfilled") {
                for (const r of result.value) {
                    // Deduplicate by text content
                    const key = r.text.slice(0, 100);
                    if (!seen.has(key)) {
                        seen.add(key);
                        merged.push(r);
                    }
                }
            }
        }
        return merged.sort((a, b) => b.score - a.score).slice(0, topK);
    }
    formatContext(results, minScore = 0.3) {
        return (0, base_js_1.formatKnowledgeContext)(results, minScore);
    }
}
exports.HybridKnowledgeStore = HybridKnowledgeStore;
