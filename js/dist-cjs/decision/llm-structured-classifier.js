"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.LLMStructuredClassifier = void 0;
const ai_1 = require("ai");
const types_js_1 = require("../types.js");
class LLMStructuredClassifier {
    name;
    model;
    schema;
    systemPrompt;
    constructor(config) {
        this.name = config.name ?? "LLMStructuredClassifier";
        this.model = config.model;
        this.schema = config.schema;
        this.systemPrompt = config.systemPrompt;
    }
    async classify(input) {
        const contextParts = [];
        if (input.summary) {
            contextParts.push(`【Conversation Summary】\n${input.summary}`);
        }
        if (input.memoryContext) {
            contextParts.push(`【User Memory】\n${input.memoryContext}`);
        }
        if (input.knowledgeContext) {
            contextParts.push(`【Knowledge】\n${input.knowledgeContext}`);
        }
        if (input.extraContext?.length) {
            contextParts.push(...input.extraContext);
        }
        const userPrompt = contextParts.length > 0
            ? `${contextParts.join("\n\n")}\n\n---\nUser message: ${input.message}`
            : input.message;
        const { object, usage } = await (0, ai_1.generateObject)({
            model: this.model,
            schema: this.schema,
            system: this.systemPrompt,
            prompt: userPrompt,
        });
        return {
            result: object,
            rawText: JSON.stringify(object),
            usage: usage ? (0, types_js_1.normalizeUsage)(usage) : undefined,
        };
    }
}
exports.LLMStructuredClassifier = LLMStructuredClassifier;
