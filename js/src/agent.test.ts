import { describe, it, expect } from "vitest";
import { z } from "zod";
import { NaruAgent } from "./agent.js";
import { tool } from "./tools/base.js";
import { KeywordGuardrail } from "./guardrails/keyword.js";
import { InMemorySessionStore } from "./session/in-memory-store.js";
import type { LanguageModel } from "ai";

/**
 * Mock LanguageModel that returns predefined responses.
 */
function createMockModel(response = "Hello! I'm a test assistant."): LanguageModel {
  return {
    specificationVersion: "v2",
    provider: "test",
    modelId: "test-model",
    supportedUrls: {},
    doGenerate: async () => ({
      content: [{ type: "text" as const, text: response }],
      finishReason: "stop" as const,
      usage: { inputTokens: 10, outputTokens: 5, totalTokens: 15 },
      warnings: [],
      response: {
        id: "test",
        timestamp: new Date(),
        modelId: "test-model",
      },
    }),
    doStream: async () => ({
      stream: new ReadableStream({
        start(controller) {
          controller.enqueue({
            type: "text-start",
            id: "t1",
          });
          controller.enqueue({
            type: "text-delta",
            id: "t1",
            delta: response,
          });
          controller.enqueue({
            type: "text-end",
            id: "t1",
          });
          controller.enqueue({
            type: "finish",
            finishReason: "stop",
            usage: { inputTokens: 10, outputTokens: 5, totalTokens: 15 },
          });
          controller.close();
        },
      }),
      warnings: [],
    }),
  } as unknown as LanguageModel;
}

describe("NaruAgent", () => {
  it("chat() returns a NaruResult with content", async () => {
    const agent = new NaruAgent({
      model: createMockModel("Hello!"),
    });

    const result = await agent.chat("Hi there");
    expect(result.content).toBe("Hello!");
    expect(result.blocked).toBe(false);
    expect(result.sessionId).toBeTruthy();
  });

  it("blocks input via guardrails", async () => {
    const agent = new NaruAgent({
      model: createMockModel(),
      guardrails: [
        new KeywordGuardrail({
          blockedPatterns: ["hack"],
          inputMessage: "Blocked!",
        }),
      ],
    });

    const result = await agent.chat("how to hack");
    expect(result.blocked).toBe(true);
    expect(result.content).toBe("Blocked!");
  });

  it("uses session store to persist history", async () => {
    const sessionStore = new InMemorySessionStore();
    const agent = new NaruAgent({
      model: createMockModel("Response 1"),
      sessionStore,
    });

    await agent.chat("Hello", { sessionId: "s1" });
    // Wait for async session save
    await new Promise((r) => setTimeout(r, 50));

    const history = await sessionStore.get("s1");
    expect(history).not.toBeNull();
    expect(history!.length).toBe(2); // user + assistant
  });

  it("includes tools in the call", async () => {
    const testTool = tool({
      name: "calculator",
      description: "Calculate math",
      parameters: z.object({ expr: z.string() }),
      execute: async ({ expr }) => `Result: ${expr}`,
    });

    const agent = new NaruAgent({
      model: createMockModel("The answer is 42"),
      tools: [testTool],
    });

    const result = await agent.chat("What is 6*7?");
    expect(result.content).toBe("The answer is 42");
  });
});
