"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.InMemorySessionStore = void 0;
class InMemorySessionStore {
    store = new Map();
    async get(sessionId) {
        return this.store.get(sessionId) ?? null;
    }
    async save(sessionId, history) {
        this.store.set(sessionId, history);
    }
    async delete(sessionId) {
        this.store.delete(sessionId);
    }
}
exports.InMemorySessionStore = InMemorySessionStore;
