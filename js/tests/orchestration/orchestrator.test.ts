import { describe, it, expect, vi } from "vitest";
import { AgentOrchestrator } from "../../src/orchestration/orchestrator.js";
import type { AgentChatDelegate } from "../../src/orchestration/orchestrator.js";
import type { OrchestrationResult } from "../../src/orchestration/result.js";
import type { NaruResult } from "../../src/types.js";

function makeMockDelegate(content = "Hello from delegate"): AgentChatDelegate {
  const mockResult: NaruResult = {
    content,
    blocked: false,
    usage: { promptTokens: 10, completionTokens: 5, totalTokens: 15 },
    intent: null,
    toolCalls: ["tool_a"],
    timings: { total: 100 },
    sessionId: "sess-1",
    traceId: "trace-1",
    trace: null,
  };
  return {
    chat: vi.fn().mockResolvedValue(mockResult),
  };
}

describe("AgentOrchestrator - AC1, AC2, AC14", () => {
  it("should satisfy AgentChatDelegate interface (nestable)", async () => {
    const inner = makeMockDelegate("inner");
    const inner2 = makeMockDelegate("inner2");
    const outer = new AgentOrchestrator({ delegate: inner });
    // outer itself satisfies AgentChatDelegate — pass as delegate to another orchestrator
    const nested = new AgentOrchestrator({ delegate: outer });
    const result = await nested.chat("test message");
    expect(result.content).toBe("inner");
    expect(inner.chat).toHaveBeenCalledWith("test message", undefined);
    // outer also satisfies AgentChatDelegate
    expect(typeof outer.chat).toBe("function");
    void inner2;
  });

  it("should pass message and options to delegate in passthrough mode", async () => {
    const delegate = makeMockDelegate("delegate response");
    const orchestrator = new AgentOrchestrator({ delegate });
    const options = { userId: "user-1", sessionId: "sess-1" };

    const result = await orchestrator.chat("Hello", options);

    expect(delegate.chat).toHaveBeenCalledWith("Hello", options);
    expect(result.content).toBe("delegate response");
    expect(result.usage).toEqual({ promptTokens: 10, completionTokens: 5, totalTokens: 15 });
    expect(result.toolCalls).toEqual(["tool_a"]);
  });

  it("should set trace.phaseReached to delegate and intent to null in passthrough mode", async () => {
    const delegate = makeMockDelegate();
    const orchestrator = new AgentOrchestrator({ delegate });
    const result = await orchestrator.chat("Hello") as OrchestrationResult;

    expect(result.decisionTrace.phaseReached).toBe("delegate");
    expect(result.orchestrationIntent).toBeNull();
    expect(result.decisionTrace.traceId).toBeTruthy();
    expect(typeof result.decisionTrace.traceId).toBe("string");
  });

  it("should include timings in trace", async () => {
    const delegate = makeMockDelegate();
    const orchestrator = new AgentOrchestrator({ delegate });
    const result = await orchestrator.chat("test") as OrchestrationResult;

    expect(result.decisionTrace.timings).toBeDefined();
    expect(typeof result.decisionTrace.timings.total).toBe("number");
    expect(result.decisionTrace.timings.total).toBeGreaterThanOrEqual(0);
  });

  it("should have OrchestrationResult backward-compatible with NaruResult", async () => {
    const delegate = makeMockDelegate("compat response");
    const orchestrator = new AgentOrchestrator({ delegate });
    const result = await orchestrator.chat("test") as OrchestrationResult;

    // All NaruResult fields present
    expect(typeof result.content).toBe("string");
    expect(typeof result.blocked).toBe("boolean");
    expect(result.usage).toBeDefined();
    expect(Array.isArray(result.toolCalls)).toBe(true);

    // New fields
    expect(result.decisionTrace).toBeDefined();
    expect("orchestrationIntent" in result).toBe(true);
    expect("pendingConfirmation" in result).toBe(true);
  });
});

describe("AgentOrchestrator - AC12: Intent-to-delegate routing", () => {
  it("should route to specific delegate based on intent.object", async () => {
    const taskAgent = makeMockDelegate("task agent response");
    const calendarAgent = makeMockDelegate("calendar response");
    const generalAgent = makeMockDelegate("general response");

    const { DeterministicIntentResolver } = await import("../../src/orchestration/intent.js");
    const resolver = new DeterministicIntentResolver([
      { pattern: /capture task/, intent: { object: "task_capture", confidence: 1.0 } },
      { pattern: /calendar/, intent: { object: "calendar_query", confidence: 1.0 } },
    ]);

    const orchestrator = new AgentOrchestrator({
      delegate: generalAgent,
      delegates: new Map([
        ["task_capture", taskAgent],
        ["calendar_query", calendarAgent],
      ]),
      intentResolver: resolver,
    });

    const result = await orchestrator.chat("capture task: buy milk") as OrchestrationResult;
    expect(result.content).toBe("task agent response");
    expect(taskAgent.chat).toHaveBeenCalled();
    expect(generalAgent.chat).not.toHaveBeenCalled();
    expect(result.decisionTrace.delegateUsed).toBe("task_capture");
  });

  it("should fallback to default delegate when intent not in delegates map", async () => {
    const generalAgent = makeMockDelegate("general response");
    const { DeterministicIntentResolver } = await import("../../src/orchestration/intent.js");
    const resolver = new DeterministicIntentResolver([
      { pattern: /hello/, intent: { object: "greeting", confidence: 0.9 } },
    ]);

    const orchestrator = new AgentOrchestrator({
      delegate: generalAgent,
      intentResolver: resolver,
    });

    const result = await orchestrator.chat("hello world") as OrchestrationResult;
    expect(result.content).toBe("general response");
    expect(generalAgent.chat).toHaveBeenCalled();
    expect(result.decisionTrace.delegateUsed).toBe("default");
  });

  it("should use default delegate when intent is unknown", async () => {
    const generalAgent = makeMockDelegate("fallback");
    const taskAgent = makeMockDelegate("task");
    const { DeterministicIntentResolver } = await import("../../src/orchestration/intent.js");
    const resolver = new DeterministicIntentResolver([]);

    const orchestrator = new AgentOrchestrator({
      delegate: generalAgent,
      delegates: new Map([["task_capture", taskAgent]]),
      intentResolver: resolver,
    });

    const result = await orchestrator.chat("random message") as OrchestrationResult;
    expect(result.content).toBe("fallback");
    expect(generalAgent.chat).toHaveBeenCalled();
    expect(taskAgent.chat).not.toHaveBeenCalled();
  });
});

describe("AgentOrchestrator - AC10: AgentDecisionTrace completeness", () => {
  it("should include all required trace fields", async () => {
    const delegate = makeMockDelegate();
    const orchestrator = new AgentOrchestrator({ delegate });
    const result = await orchestrator.chat("test") as OrchestrationResult;

    expect(result.decisionTrace.traceId).toBeTruthy();
    expect(["pending_confirmation", "direct_execution", "delegate", "blocked"]).toContain(result.decisionTrace.phaseReached);
    expect("intentResolved" in result.decisionTrace).toBe(true);
    expect(result.decisionTrace.timings).toBeDefined();
    expect(typeof result.decisionTrace.timings.total).toBe("number");
    expect("directExecutorUsed" in result.decisionTrace).toBe(true);
    expect("delegateUsed" in result.decisionTrace).toBeDefined();
  });
});
