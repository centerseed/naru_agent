"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.formatMemoryContext = formatMemoryContext;
/**
 * Format memory items into a context string for LLM injection.
 */
function formatMemoryContext(memories) {
    if (memories.length === 0)
        return "";
    return "User memories:\n" + memories.map((m) => `- ${m.content}`).join("\n");
}
