import { describe, it, expect } from "vitest";
import { AgentOrchestrator } from "../../src/orchestration/orchestrator.js";
import type { OrchestrationResult } from "../../src/orchestration/result.js";
import { makeMockNaruResult } from "./helpers.js";

describe("OrchestrationResult - AC14", () => {
  it("should include all NaruResult fields", async () => {
    const orchestrator = new AgentOrchestrator({
      delegate: { chat: async () => makeMockNaruResult() },
    });

    const result = await orchestrator.chat("hello") as OrchestrationResult;

    // NaruResult fields
    expect(typeof result.content).toBe("string");
    expect(typeof result.blocked).toBe("boolean");
    expect(result.usage).toHaveProperty("promptTokens");
    expect(result.usage).toHaveProperty("completionTokens");
    expect(result.usage).toHaveProperty("totalTokens");
    expect(Array.isArray(result.toolCalls)).toBe(true);
  });

  it("should include new orchestration fields", async () => {
    const orchestrator = new AgentOrchestrator({
      delegate: { chat: async () => makeMockNaruResult() },
    });

    const result = await orchestrator.chat("hello") as OrchestrationResult;

    // New fields
    expect("orchestrationIntent" in result).toBe(true);
    expect("decisionTrace" in result).toBe(true);
    expect("pendingConfirmation" in result).toBe(true);
  });

  it("should have intent as null when no resolver configured", async () => {
    const orchestrator = new AgentOrchestrator({
      delegate: { chat: async () => makeMockNaruResult() },
    });

    const result = await orchestrator.chat("hello") as OrchestrationResult;
    expect(result.orchestrationIntent).toBeNull();
  });

  it("should always have decisionTrace present", async () => {
    const orchestrator = new AgentOrchestrator({
      delegate: { chat: async () => makeMockNaruResult() },
    });

    const result = await orchestrator.chat("hello") as OrchestrationResult;
    expect(result.decisionTrace).toBeDefined();
    expect(result.decisionTrace).not.toBeNull();
    expect(result.decisionTrace.traceId).toBeTruthy();
    expect(result.decisionTrace.phaseReached).toBe("delegate");
  });

  it("should have pendingConfirmation as null by default", async () => {
    const orchestrator = new AgentOrchestrator({
      delegate: { chat: async () => makeMockNaruResult() },
    });

    const result = await orchestrator.chat("hello") as OrchestrationResult;
    expect(result.pendingConfirmation).toBeNull();
  });

  it("should preserve delegate content and toolCalls exactly", async () => {
    const orchestrator = new AgentOrchestrator({
      delegate: {
        chat: async () => makeMockNaruResult({
          content: "specific content",
          toolCalls: ["weather_lookup", "calendar_create"],
        }),
      },
    });

    const result = await orchestrator.chat("check weather") as OrchestrationResult;
    expect(result.content).toBe("specific content");
    expect(result.toolCalls).toEqual(["weather_lookup", "calendar_create"]);
  });
});
