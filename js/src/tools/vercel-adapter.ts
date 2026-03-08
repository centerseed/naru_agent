import { tool as vercelTool, type ToolSet } from "ai";
import type { BaseTool } from "./base.js";

/**
 * Convert naru BaseTool[] to Vercel AI SDK ToolSet record.
 *
 * @example
 * const tools = toVercelTools([weatherTool, searchTool]);
 * const result = await generateText({ model, tools, prompt: "..." });
 */
export function toVercelTools(
  tools: BaseTool[],
): ToolSet {
  const result: Record<string, unknown> = {};
  for (const t of tools) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    result[t.name] = (vercelTool as any)({
      description: t.description,
      parameters: t.parameters,
      execute: async (params: Record<string, unknown>) => {
        return t.execute(params);
      },
    });
  }
  return result as ToolSet;
}
