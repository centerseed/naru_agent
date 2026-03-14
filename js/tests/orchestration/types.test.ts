import { describe, it, expect } from "vitest";
import type {
  GenericIntentObject,
  OrchestratorIntent,
  BaseIntentResolver,
} from "../../src/orchestration/intent.js";
import { DeterministicIntentResolver } from "../../src/orchestration/intent.js";
import { AgentOrchestrator } from "../../src/orchestration/orchestrator.js";
import { makeMockNaruResult } from "./helpers.js";

// AC11: Custom intent types via TypeScript generics
type MyIntent = GenericIntentObject | "task_capture" | "calendar_query" | "reorganize";

describe("TypeScript Generics - AC11", () => {
  it("should allow DeterministicIntentResolver with custom intent type", async () => {
    // This test verifies TypeScript generics work at the type level
    // If it compiles, it's correct
    const resolver = new DeterministicIntentResolver<MyIntent>([
      { pattern: /整理/, intent: { object: "reorganize", confidence: 1.0 } },
      { pattern: /capture/, intent: { object: "task_capture", confidence: 1.0 } },
      { pattern: /calendar/, intent: { object: "calendar_query", confidence: 0.9 } },
    ]);

    const result1 = await resolver.resolve({ message: "整理一下" });
    expect(result1.object).toBe("reorganize");

    const result2 = await resolver.resolve({ message: "capture task" });
    expect(result2.object).toBe("task_capture");

    const result3 = await resolver.resolve({ message: "unknown" });
    expect(result3.object).toBe("unknown");
  });

  it("should allow AgentOrchestrator with custom intent type", async () => {
    const resolver = new DeterministicIntentResolver<MyIntent>([
      { pattern: /capture/, intent: { object: "task_capture", confidence: 1.0 } },
    ]);

    const taskAgent = { chat: async () => makeMockNaruResult({ content: "task" }) };
    const generalAgent = { chat: async () => makeMockNaruResult({ content: "general" }) };

    // delegates map key should be MyIntent type
    const orchestrator = new AgentOrchestrator<MyIntent>({
      delegate: generalAgent,
      delegates: new Map<MyIntent, typeof taskAgent>([
        ["task_capture", taskAgent],
      ]),
      intentResolver: resolver,
    });

    const result = await orchestrator.chat("capture task: buy milk");
    expect(result.content).toBe("task");
  });

  it("should provide GenericIntentObject as built-in type", async () => {
    // GenericIntentObject should include standard intents
    const resolver = new DeterministicIntentResolver<GenericIntentObject>([
      { pattern: /hello/, intent: { object: "greeting", confidence: 0.9 } },
      { pattern: /search/, intent: { object: "query", confidence: 0.8 } },
      { pattern: /do|make|create/, intent: { object: "action", confidence: 0.8 } },
    ]);

    const greeting = await resolver.resolve({ message: "hello world" });
    expect(greeting.object).toBe("greeting");

    const query = await resolver.resolve({ message: "search for files" });
    expect(query.object).toBe("query");

    const unknown = await resolver.resolve({ message: "something else" });
    expect(unknown.object).toBe("unknown");
  });

  it("should type IntentResult with custom intent", () => {
    // Type-level test — if this compiles, it passes
    const intentResult: OrchestratorIntent<MyIntent> = {
      object: "task_capture",
      confidence: 0.95,
      requiresConfirmation: false,
    };

    expect(intentResult.object).toBe("task_capture");
    expect(intentResult.confidence).toBe(0.95);
    expect(intentResult.requiresConfirmation).toBe(false);
  });

  it("should allow BaseIntentResolver interface with custom type", async () => {
    // Custom resolver implementing the interface
    const customResolver: BaseIntentResolver<MyIntent> = {
      resolve: async (input) => {
        if (input.message.includes("重組")) {
          return { object: "reorganize", confidence: 1.0 };
        }
        return { object: "unknown", confidence: 0 };
      },
    };

    const result = await customResolver.resolve({ message: "重組資料夾" });
    expect(result.object).toBe("reorganize");
  });
});
