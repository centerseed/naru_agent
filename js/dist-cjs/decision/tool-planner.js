"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.ToolPlanner = void 0;
const ai_1 = require("ai");
const vercel_adapter_js_1 = require("../tools/vercel-adapter.js");
class ToolPlanner {
    model;
    systemPrompt;
    constructor(config) {
        this.model = config.model;
        this.systemPrompt = config.systemPrompt;
    }
    async plan(message, tools) {
        if (tools.length === 0)
            return [];
        const result = await (0, ai_1.generateText)({
            model: this.model,
            system: this.systemPrompt ??
                "You are a tool planner. Given the user message, decide which tools to call and with what arguments. Call the appropriate tools.",
            prompt: message,
            tools: (0, vercel_adapter_js_1.toVercelToolsNoop)(tools),
            toolChoice: "auto",
            stopWhen: (0, ai_1.stepCountIs)(1),
        });
        const plans = [];
        for (const step of result.steps ?? []) {
            for (const tc of step.toolCalls ?? []) {
                plans.push({
                    tool: tc.toolName,
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    args: tc.args,
                });
            }
        }
        return plans;
    }
}
exports.ToolPlanner = ToolPlanner;
