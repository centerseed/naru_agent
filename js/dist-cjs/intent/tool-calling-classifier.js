"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.LLMToolCallingClassifier = void 0;
const ai_1 = require("ai");
const vercel_adapter_js_1 = require("../tools/vercel-adapter.js");
/**
 * Uses a lightweight LLM to decide which tools to call, then executes them.
 */
class LLMToolCallingClassifier {
    model;
    systemPrompt;
    constructor(config) {
        this.model = config.model;
        this.systemPrompt =
            config.systemPrompt ??
                "You are a tool-calling assistant. Use the available tools to answer the user's question. Only call tools that are relevant.";
    }
    async classify(message, tools) {
        if (tools.length === 0) {
            return { toolResults: [], usage: {}, rawResponse: "" };
        }
        const vercelTools = (0, vercel_adapter_js_1.toVercelTools)(tools);
        const result = await (0, ai_1.generateText)({
            model: this.model,
            system: this.systemPrompt,
            prompt: message,
            tools: vercelTools,
            stopWhen: (0, ai_1.stepCountIs)(1),
        });
        const toolResults = [];
        // Extract tool call results from steps
        for (const step of result.steps ?? []) {
            for (const tc of step.toolCalls ?? []) {
                toolResults.push({
                    tool: tc.toolName,
                    args: tc.input ?? {},
                    result: "",
                });
            }
            // Match tool results by index
            const stepToolResults = step.toolResults ?? [];
            for (let i = 0; i < stepToolResults.length && i < toolResults.length; i++) {
                toolResults[toolResults.length - (stepToolResults.length - i)] = {
                    ...toolResults[toolResults.length - (stepToolResults.length - i)],
                    result: String(stepToolResults[i].result),
                };
            }
        }
        return {
            toolResults,
            usage: {
                promptTokens: result.usage?.inputTokens ?? 0,
                completionTokens: result.usage?.outputTokens ?? 0,
            },
            rawResponse: result.text,
        };
    }
}
exports.LLMToolCallingClassifier = LLMToolCallingClassifier;
