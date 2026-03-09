"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.KeywordGuardrail = void 0;
class KeywordGuardrail {
    patterns;
    inputMessage;
    outputReplacement;
    constructor(config) {
        const flags = config.caseSensitive ? "" : "i";
        this.patterns = config.blockedPatterns.map((p) => new RegExp(p, flags));
        this.inputMessage =
            config.inputMessage ?? "This request cannot be processed.";
        this.outputReplacement = config.outputReplacement ?? null;
    }
    async checkInput(message) {
        for (const pattern of this.patterns) {
            if (pattern.test(message)) {
                return {
                    passed: false,
                    modifiedText: null,
                    reason: this.inputMessage,
                };
            }
        }
        return { passed: true, modifiedText: null, reason: null };
    }
    async checkOutput(response) {
        for (const pattern of this.patterns) {
            if (pattern.test(response)) {
                return {
                    passed: false,
                    modifiedText: this.outputReplacement,
                    reason: `Output matched blocked pattern: ${pattern.source}`,
                };
            }
        }
        return { passed: true, modifiedText: null, reason: null };
    }
}
exports.KeywordGuardrail = KeywordGuardrail;
