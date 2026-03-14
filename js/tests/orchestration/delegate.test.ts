import { describe, it, expect } from "vitest";
import { AgentOrchestrator } from "../../src/orchestration/orchestrator.js";
import type { AgentChatDelegate } from "../../src/orchestration/orchestrator.js";
import { makeMockNaruResult } from "./helpers.js";

describe("AgentChatDelegate - AC1", () => {
  it("should accept any object with a chat() method as delegate", () => {
    // TypeScript structural typing check — this must compile
    const simpleDelegate: AgentChatDelegate = {
      chat: async (message: string) => makeMockNaruResult({ content: `Echo: ${message}` }),
    };

    const orchestrator = new AgentOrchestrator({ delegate: simpleDelegate });
    expect(orchestrator).toBeDefined();
    expect(typeof orchestrator.chat).toBe("function");
  });

  it("should satisfy AgentChatDelegate interface itself (nestable)", () => {
    const innerDelegate: AgentChatDelegate = {
      chat: async () => makeMockNaruResult({ content: "inner" }),
    };
    const innerOrchestrator = new AgentOrchestrator({ delegate: innerDelegate });

    // AgentOrchestrator itself can be used as a delegate
    const outerOrchestrator = new AgentOrchestrator({
      delegate: innerOrchestrator, // nestable!
    });

    expect(outerOrchestrator).toBeDefined();
    expect(typeof outerOrchestrator.chat).toBe("function");
  });

  it("should correctly forward chat to nested orchestrators", async () => {
    const innerDelegate: AgentChatDelegate = {
      chat: async (message: string) => makeMockNaruResult({ content: `Nested: ${message}` }),
    };
    const inner = new AgentOrchestrator({ delegate: innerDelegate });
    const outer = new AgentOrchestrator({ delegate: inner });

    const result = await outer.chat("test message");
    expect(result.content).toBe("Nested: test message");
  });

  it("should accept NaruAgent-like objects (structural duck typing)", () => {
    // Simulate a NaruAgent-like object — as long as it has chat()
    const naruAgentLike = {
      chat: async (_message: string, _options?: unknown) => makeMockNaruResult({ content: "naru response" }),
      getEventBus: () => ({}), // extra methods are fine
      chatStream: async function* () { yield "stream"; }, // extra methods are fine
    };

    // This should compile without errors
    const orchestrator = new AgentOrchestrator({
      delegate: naruAgentLike as AgentChatDelegate,
    });
    expect(orchestrator).toBeDefined();
  });
});
