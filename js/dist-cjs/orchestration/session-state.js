"use strict";
/**
 * AgentSessionState — tracks entities presented in the last response for coreference resolution.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.InMemorySessionStateStore = void 0;
/**
 * InMemorySessionStateStore — simple in-memory Map implementation.
 */
class InMemorySessionStateStore {
    store = new Map();
    async get(sessionId) {
        return this.store.get(sessionId) ?? null;
    }
    async save(sessionId, state) {
        this.store.set(sessionId, state);
    }
    async clear(sessionId) {
        this.store.delete(sessionId);
    }
}
exports.InMemorySessionStateStore = InMemorySessionStateStore;
