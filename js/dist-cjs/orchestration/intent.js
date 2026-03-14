"use strict";
/**
 * Generic intent types and resolvers for the orchestration layer.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.LLMFallbackIntentResolver = exports.DeterministicIntentResolver = void 0;
/**
 * DeterministicIntentResolver — fast pattern matching, no LLM calls.
 * Returns first matching pattern or unknown with confidence 0.
 */
class DeterministicIntentResolver {
    patterns;
    constructor(patterns) {
        this.patterns = patterns;
    }
    async resolve(input) {
        for (const entry of this.patterns) {
            if (entry.pattern.test(input.message)) {
                return entry.intent;
            }
        }
        return { object: "unknown", confidence: 0 };
    }
}
exports.DeterministicIntentResolver = DeterministicIntentResolver;
/**
 * LLMFallbackIntentResolver — tries deterministic first, falls back to LLM classifier.
 */
class LLMFallbackIntentResolver {
    primary;
    fallbackAgent;
    parseResponse;
    constructor(config) {
        this.primary = config.primary;
        this.fallbackAgent = config.fallbackAgent;
        this.parseResponse = config.parseResponse;
    }
    async resolve(input) {
        const primaryResult = await this.primary.resolve(input);
        if (primaryResult.object !== "unknown") {
            return primaryResult;
        }
        // Fallback to LLM
        const llmResponse = await this.fallbackAgent.chat(`Classify the intent of this message: "${input.message}". Return a JSON object with "object" (string) and "confidence" (number 0-1).`);
        if (this.parseResponse) {
            return this.parseResponse(llmResponse.content);
        }
        // Default parsing
        try {
            const parsed = JSON.parse(llmResponse.content);
            return {
                object: (parsed.object ?? "unknown"),
                confidence: parsed.confidence ?? 0.5,
            };
        }
        catch {
            return { object: "unknown", confidence: 0 };
        }
    }
}
exports.LLMFallbackIntentResolver = LLMFallbackIntentResolver;
