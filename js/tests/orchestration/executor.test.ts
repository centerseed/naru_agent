import { describe, it, expect, vi } from "vitest";
import { AgentOrchestrator } from "../../src/orchestration/orchestrator.js";
import type { BaseDirectExecutor } from "../../src/orchestration/executor.js";
import type { OrchestrationResult } from "../../src/orchestration/result.js";
import type { OrchestratorIntent } from "../../src/orchestration/intent.js";
import { DeterministicIntentResolver } from "../../src/orchestration/intent.js";
import { makeMockNaruResult } from "./helpers.js";

function makeMockOrchestrationResult(content: string): OrchestrationResult {
  return {
    content,
    blocked: false,
    usage: { promptTokens: 0, completionTokens: 0, totalTokens: 0 },
    intent: null,
    toolCalls: [],
    timings: {},
    sessionId: null,
    traceId: null,
    trace: null,
    decisionTrace: {
      traceId: "exec-trace",
      phaseReached: "direct_execution",
      intentResolved: null,
      timings: { total: 0 },
      directExecutorUsed: "task-executor",
      delegateUsed: null,
    },
    orchestrationIntent: null,
    pendingConfirmation: null,
  };
}

describe("BaseDirectExecutor - AC5", () => {
  it("should call executor when canHandle returns true and skip delegate", async () => {
    const executorResult = makeMockOrchestrationResult("executed directly");
    const executor: BaseDirectExecutor<string> = {
      name: "task-executor",
      canHandle: vi.fn().mockReturnValue(true),
      execute: vi.fn().mockResolvedValue(executorResult),
    };
    const delegate = { chat: vi.fn().mockResolvedValue(makeMockNaruResult({ content: "delegate" })) };
    const resolver = new DeterministicIntentResolver([
      { pattern: /capture/, intent: { object: "task_capture", confidence: 0.95 } },
    ]);

    const orchestrator = new AgentOrchestrator({
      delegate,
      intentResolver: resolver,
      directExecutors: [executor],
    });

    const result = await orchestrator.chat("capture task: buy milk") as OrchestrationResult;

    expect(executor.execute).toHaveBeenCalled();
    expect(delegate.chat).not.toHaveBeenCalled();
    expect(result.decisionTrace.phaseReached).toBe("direct_execution");
    expect(result.decisionTrace.directExecutorUsed).toBe("task-executor");
  });

  it("should fallthrough to delegate when executor.execute returns null", async () => {
    const executor: BaseDirectExecutor<string> = {
      name: "noop-executor",
      canHandle: vi.fn().mockReturnValue(true),
      execute: vi.fn().mockResolvedValue(null),
    };
    const delegate = { chat: vi.fn().mockResolvedValue(makeMockNaruResult({ content: "delegate fallback" })) };
    const resolver = new DeterministicIntentResolver([
      { pattern: /anything/, intent: { object: "action", confidence: 0.8 } },
    ]);

    const orchestrator = new AgentOrchestrator({
      delegate,
      intentResolver: resolver,
      directExecutors: [executor],
    });

    const result = await orchestrator.chat("anything goes") as OrchestrationResult;

    expect(executor.execute).toHaveBeenCalled();
    expect(delegate.chat).toHaveBeenCalled();
    expect(result.decisionTrace.phaseReached).toBe("delegate");
    expect(result.content).toBe("delegate fallback");
  });

  it("should skip executor when canHandle returns false", async () => {
    const executor: BaseDirectExecutor<string> = {
      name: "selective-executor",
      canHandle: vi.fn().mockReturnValue(false),
      execute: vi.fn(),
    };
    const delegate = { chat: vi.fn().mockResolvedValue(makeMockNaruResult({ content: "delegate" })) };
    const resolver = new DeterministicIntentResolver([
      { pattern: /hello/, intent: { object: "greeting", confidence: 0.9 } },
    ]);

    const orchestrator = new AgentOrchestrator({
      delegate,
      intentResolver: resolver,
      directExecutors: [executor],
    });

    const result = await orchestrator.chat("hello world") as OrchestrationResult;

    expect(executor.execute).not.toHaveBeenCalled();
    expect(delegate.chat).toHaveBeenCalled();
    expect(result.decisionTrace.directExecutorUsed).toBeNull();
  });

  it("should try executors in order and stop at first successful one", async () => {
    const firstExecutorResult = makeMockOrchestrationResult("first executor");
    const firstExecutor: BaseDirectExecutor<string> = {
      name: "first",
      canHandle: vi.fn().mockReturnValue(true),
      execute: vi.fn().mockResolvedValue(firstExecutorResult),
    };
    const secondExecutor: BaseDirectExecutor<string> = {
      name: "second",
      canHandle: vi.fn().mockReturnValue(true),
      execute: vi.fn().mockResolvedValue(null),
    };
    const delegate = { chat: vi.fn() };
    const resolver = new DeterministicIntentResolver([
      { pattern: /test/, intent: { object: "action", confidence: 1.0 } },
    ]);

    const orchestrator = new AgentOrchestrator({
      delegate,
      intentResolver: resolver,
      directExecutors: [firstExecutor, secondExecutor],
    });

    const result = await orchestrator.chat("test message") as OrchestrationResult;

    expect(firstExecutor.execute).toHaveBeenCalled();
    expect(secondExecutor.execute).not.toHaveBeenCalled();
    expect(delegate.chat).not.toHaveBeenCalled();
    expect(result.decisionTrace.directExecutorUsed).toBe("first");
  });
});
