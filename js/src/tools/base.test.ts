import { describe, it, expect } from "vitest";
import { z } from "zod";
import { tool } from "./base.js";
import { toVercelTools } from "./vercel-adapter.js";

describe("tool()", () => {
  it("creates a tool with name, description, parameters, and execute", async () => {
    const weatherTool = tool({
      name: "get_weather",
      description: "Get weather for a city",
      parameters: z.object({ city: z.string() }),
      execute: async ({ city }) => `Sunny in ${city}`,
    });

    expect(weatherTool.name).toBe("get_weather");
    expect(weatherTool.description).toBe("Get weather for a city");
    expect(await weatherTool.execute({ city: "Taipei" })).toBe("Sunny in Taipei");
  });
});

describe("toVercelTools()", () => {
  it("converts BaseTool[] to Vercel AI SDK CoreTool record", () => {
    const t = tool({
      name: "test",
      description: "A test tool",
      parameters: z.object({ x: z.number() }),
      execute: async ({ x }) => String(x * 2),
    });

    const vercelTools = toVercelTools([t]);
    expect(vercelTools).toHaveProperty("test");
    expect(vercelTools.test.description).toBe("A test tool");
  });
});
