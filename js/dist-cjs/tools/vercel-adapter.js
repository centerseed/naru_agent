"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.toVercelTools = toVercelTools;
exports.toVercelToolsNoop = toVercelToolsNoop;
const ai_1 = require("ai");
/**
 * Convert naru BaseTool[] to Vercel AI SDK ToolSet record.
 *
 * @example
 * const tools = toVercelTools([weatherTool, searchTool]);
 * const result = await generateText({ model, tools, prompt: "..." });
 */
function toVercelTools(tools) {
    const result = {};
    for (const t of tools) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        result[t.name] = ai_1.tool({
            description: t.description,
            parameters: t.parameters,
            execute: async (params) => {
                const maxAttempts = (t.retries ?? 0) + 1;
                for (let attempt = 1; attempt <= maxAttempts; attempt++) {
                    try {
                        const exec = t.execute(params);
                        if (t.timeout != null) {
                            let timerId;
                            const timeout = new Promise((_, reject) => {
                                timerId = setTimeout(() => reject(new Error(`Timed out after ${t.timeout}ms`)), t.timeout);
                            });
                            try {
                                return await Promise.race([exec, timeout]);
                            }
                            finally {
                                clearTimeout(timerId);
                            }
                        }
                        return await exec;
                    }
                    catch (err) {
                        const msg = err instanceof Error ? err.message : String(err);
                        if (attempt >= maxAttempts) {
                            return `[Tool Error] ${t.name}: ${msg}`;
                        }
                    }
                }
                // unreachable, but satisfies TS
                return `[Tool Error] ${t.name}: unknown failure`;
            },
        });
    }
    return result;
}
/**
 * Same as toVercelTools but with a no-op execute.
 * Useful for tool planning where you need LLM tool selection
 * without actually executing tools.
 */
function toVercelToolsNoop(tools) {
    const result = {};
    for (const t of tools) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        result[t.name] = ai_1.tool({
            description: t.description,
            parameters: t.parameters,
            execute: async () => "",
        });
    }
    return result;
}
