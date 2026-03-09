"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.EmbeddingSkillSelector = exports.KeywordSkillSelector = void 0;
const math_js_1 = require("../utils/math.js");
/**
 * Case-insensitive keyword matching on skill triggers.
 */
class KeywordSkillSelector {
    async select(skills, message) {
        const lower = message.toLowerCase();
        return skills.filter((s) => s.alwaysActive ||
            s.triggers.some((t) => lower.includes(t.toLowerCase())));
    }
}
exports.KeywordSkillSelector = KeywordSkillSelector;
/**
 * Embedding-based similarity matching for skill selection.
 */
class EmbeddingSkillSelector {
    embedFn;
    topK;
    similarityThreshold;
    cachedEmbeddings = null;
    constructor(embedFn, topK = 2, similarityThreshold = 0.45) {
        this.embedFn = embedFn;
        this.topK = topK;
        this.similarityThreshold = similarityThreshold;
    }
    async select(skills, message) {
        const alwaysActive = skills.filter((s) => s.alwaysActive);
        const candidates = skills.filter((s) => !s.alwaysActive);
        if (candidates.length === 0)
            return alwaysActive;
        // Build skill description embeddings (cached)
        if (!this.cachedEmbeddings) {
            const descriptions = candidates.map((s) => `${s.name}: ${s.description} ${s.triggers.join(" ")}`);
            const embeddings = await this.embedFn(descriptions);
            this.cachedEmbeddings = new Map();
            for (let i = 0; i < candidates.length; i++) {
                this.cachedEmbeddings.set(candidates[i].name, embeddings[i]);
            }
        }
        const [queryEmbed] = await this.embedFn([message]);
        const scored = candidates
            .map((s) => ({
            skill: s,
            score: (0, math_js_1.cosineSimilarity)(queryEmbed, this.cachedEmbeddings.get(s.name)),
        }))
            .filter((x) => x.score >= this.similarityThreshold)
            .sort((a, b) => b.score - a.score)
            .slice(0, this.topK)
            .map((x) => x.skill);
        return [...alwaysActive, ...scored];
    }
}
exports.EmbeddingSkillSelector = EmbeddingSkillSelector;
