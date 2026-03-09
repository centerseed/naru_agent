"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.cosineSimilarity = cosineSimilarity;
exports.toVectorLiteral = toVectorLiteral;
function cosineSimilarity(a, b) {
    let dot = 0, normA = 0, normB = 0;
    for (let i = 0; i < a.length; i++) {
        dot += a[i] * b[i];
        normA += a[i] * a[i];
        normB += b[i] * b[i];
    }
    const denom = Math.sqrt(normA) * Math.sqrt(normB);
    return denom === 0 ? 0 : dot / denom;
}
function toVectorLiteral(embedding) {
    return `[${embedding.join(",")}]`;
}
