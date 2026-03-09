"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.LLMIntentClassifier = void 0;
const ai_1 = require("ai");
/**
 * Fast LLM-based intent classifier using 2-char codes:
 * YY = needs knowledge + needs tools
 * YN = needs knowledge, no tools
 * NY = no knowledge, needs tools
 * NN = neither
 */
class LLMIntentClassifier {
    model;
    examples;
    maxTokens;
    constructor(config) {
        this.model = config.model;
        this.examples = config.examples ?? [];
        this.maxTokens = config.maxTokens ?? 30;
    }
    async classify(message) {
        const examplesStr = this.examples
            .map(([msg, code]) => `User: ${msg}\nCode: ${code}`)
            .join("\n");
        const system = [
            "Classify user intent with a 2-character code.",
            "First char: Y if the query needs knowledge/RAG retrieval, N if not.",
            "Second char: Y if the query needs tool calls, N if not.",
            "Reply ONLY with the 2-char code (YY, YN, NY, or NN).",
            examplesStr ? `\nExamples:\n${examplesStr}` : "",
        ].join("\n");
        try {
            const result = await (0, ai_1.generateText)({
                model: this.model,
                system,
                prompt: message,
                maxOutputTokens: this.maxTokens,
            });
            const raw = result.text.trim().toUpperCase().slice(0, 2);
            return {
                needsKnowledge: raw[0] !== "N",
                needsTools: raw[1] !== "N",
                raw,
            };
        }
        catch {
            // Default: enable everything
            return { needsKnowledge: true, needsTools: true, raw: "YY" };
        }
    }
}
exports.LLMIntentClassifier = LLMIntentClassifier;
