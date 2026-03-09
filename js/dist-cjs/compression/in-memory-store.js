"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.InMemorySummaryStore = void 0;
class InMemorySummaryStore {
    store = new Map();
    async get(sessionId) {
        return this.store.get(sessionId) ?? null;
    }
    async save(sessionId, summary) {
        this.store.set(sessionId, summary);
    }
    async delete(sessionId) {
        this.store.delete(sessionId);
    }
}
exports.InMemorySummaryStore = InMemorySummaryStore;
