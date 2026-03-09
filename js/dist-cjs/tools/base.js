"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.tool = tool;
/**
 * Factory function to create a tool (equivalent to Python @tool decorator).
 *
 * @example
 * const weatherTool = tool({
 *   name: "get_weather",
 *   description: "Get weather for a city",
 *   parameters: z.object({ city: z.string() }),
 *   execute: async ({ city }) => `Weather in ${city}: sunny`,
 * });
 */
function tool(config) {
    return {
        name: config.name,
        description: config.description,
        parameters: config.parameters,
        execute: config.execute,
        timeout: config.timeout,
        retries: config.retries,
    };
}
