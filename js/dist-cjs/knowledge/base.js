"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.formatKnowledgeContext = formatKnowledgeContext;
/**
 * Default formatContext implementation.
 */
function formatKnowledgeContext(results, minScore = 0.3) {
    const filtered = results.filter((r) => r.score >= minScore);
    if (filtered.length === 0)
        return "";
    return filtered.map((r) => r.text).join("\n\n---\n\n");
}
