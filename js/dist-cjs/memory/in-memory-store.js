"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.InMemoryMemoryStore = void 0;
const math_js_1 = require("../utils/math.js");
class InMemoryMemoryStore {
    items = new Map();
    async add(item, embedding) {
        this.items.set(item.id, { item, embedding });
    }
    async search(userId, embedding, topK = 5) {
        const userItems = [...this.items.values()].filter((x) => x.item.userId === userId);
        return userItems
            .map((x) => ({
            item: x.item,
            score: (0, math_js_1.cosineSimilarity)(embedding, x.embedding),
        }))
            .sort((a, b) => b.score - a.score)
            .slice(0, topK)
            .map((x) => ({ ...x.item, score: x.score }));
    }
    async update(itemId, content, embedding) {
        const existing = this.items.get(itemId);
        if (existing) {
            existing.item.content = content;
            existing.item.updatedAt = new Date();
            existing.embedding = embedding;
        }
    }
    async delete(itemId) {
        this.items.delete(itemId);
    }
    async getAll(userId) {
        return [...this.items.values()]
            .filter((x) => x.item.userId === userId)
            .map((x) => x.item);
    }
}
exports.InMemoryMemoryStore = InMemoryMemoryStore;
