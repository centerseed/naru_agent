"use strict";
/**
 * Pending state management — tracks confirmations awaiting user response.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.InMemoryPendingStateManager = void 0;
exports.classifyConfirmationDisposition = classifyConfirmationDisposition;
/**
 * InMemoryPendingStateManager — simple in-memory Map implementation.
 */
class InMemoryPendingStateManager {
    store = new Map();
    async getPending(sessionId) {
        return this.store.get(sessionId) ?? null;
    }
    async setPending(sessionId, state) {
        this.store.set(sessionId, state);
    }
    async clearPending(sessionId) {
        this.store.delete(sessionId);
    }
}
exports.InMemoryPendingStateManager = InMemoryPendingStateManager;
const CONFIRM_PATTERN = /^(好|確認|對|yes|y|ok|好的|是|沒問題|sure|confirm)$/i;
const REJECT_PATTERN = /^(不要|取消|no|n|不|cancel|否|算了|不行|reject)$/i;
/**
 * Default implementation to classify a user message's disposition toward a pending confirmation.
 */
function classifyConfirmationDisposition(message) {
    const trimmed = message.trim();
    if (CONFIRM_PATTERN.test(trimmed))
        return "confirm";
    if (REJECT_PATTERN.test(trimmed))
        return "reject";
    return "override";
}
