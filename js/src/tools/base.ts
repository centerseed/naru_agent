import { z } from "zod";

export interface BaseTool<TParams extends z.ZodType = z.ZodType> {
  name: string;
  description: string;
  parameters: TParams;
  execute: (params: z.infer<TParams>) => Promise<string>;
}

export interface ToolConfig<TParams extends z.ZodType = z.ZodType> {
  name: string;
  description: string;
  parameters: TParams;
  execute: (params: z.infer<TParams>) => Promise<string>;
}

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
export function tool<TParams extends z.ZodType>(
  config: ToolConfig<TParams>,
): BaseTool<TParams> {
  return {
    name: config.name,
    description: config.description,
    parameters: config.parameters,
    execute: config.execute,
  };
}
