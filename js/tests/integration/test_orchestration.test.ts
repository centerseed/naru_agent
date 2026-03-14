/**
 * Orchestration Integration Tests — @ac11, @ac12, @ac13, @ac14 (@js-only)
 *
 * Covers:
 *   @ac11 — 單一 Agent Passthrough
 *   @ac12 — Intent 路由
 *   @ac13 — Direct Executor 繞過 LLM
 *   @ac14 — 多步驟確認流程
 *
 * Note: Uses mock delegates (not real LLM) to test routing logic.
 *       Only orchestration logic is tested here; LLM quality is tested elsewhere.
 *
 * Execute:
 *   GOOGLE_GENERATIVE_AI_API_KEY=xxx npx vitest run tests/integration/test_orchestration.test.ts
 */

import { describe, it, expect } from "vitest";
import {
  AgentOrchestrator,
  DeterministicIntentResolver,
  InMemoryPendingStateManager,
} from "../../src/index.js";
import type {
  AgentChatDelegate,
  OrchestrationResult,
  OrchestratorIntent,
  BaseDirectExecutor,
} from "../../src/index.js";
import type { NaruResult } from "../../src/types.js";
import { loadScenarios } from "./scenario-runner.js";

const _scenarios = loadScenarios("orchestration.json");

// ---------------------------------------------------------------------------
// Mock delegate factory
// ---------------------------------------------------------------------------

function mockDelegate(name: string, response = "mock response"): AgentChatDelegate {
  return {
    async chat(_message: string): Promise<NaruResult> {
      return {
        content: `[${name}] ${response}`,
        blocked: false,
        usage: { promptTokens: 10, completionTokens: 10, totalTokens: 20 },
        intent: null,
        toolCalls: [],
        timings: { total: 1 },
        sessionId: null,
        traceId: null,
        trace: null,
      };
    },
  };
}

// ---------------------------------------------------------------------------
// @ac11 — 單一 Agent Passthrough
// ---------------------------------------------------------------------------

describe("Orchestration_Passthrough (@ac11)", () => {
  it("single agent passthrough returns delegate response", async () => {
    const delegate = mockDelegate("default");
    const orchestrator = new AgentOrchestrator({ delegate });

    const result = await orchestrator.chat("你好");

    expect(result.blocked).toBe(false);
    expect(result.content.length).toBeGreaterThan(0);
  });

  it("passes through options to delegate", async () => {
    let receivedOptions: Record<string, unknown> | undefined;
    const delegate: AgentChatDelegate = {
      async chat(_message: string, options?: Record<string, unknown>): Promise<NaruResult> {
        receivedOptions = options;
        return {
          content: "response",
          blocked: false,
          usage: { promptTokens: 0, completionTokens: 0, totalTokens: 0 },
          intent: null,
          toolCalls: [],
          timings: {},
          sessionId: null,
          traceId: null,
          trace: null,
        };
      },
    };

    const orchestrator = new AgentOrchestrator({ delegate });
    await orchestrator.chat("test", { userId: "u1", sessionId: "s1" });

    expect(receivedOptions?.userId).toBe("u1");
    expect(receivedOptions?.sessionId).toBe("s1");
  });
});

// ---------------------------------------------------------------------------
// @ac12 — Intent 路由
// ---------------------------------------------------------------------------

describe("Orchestration_IntentRouting (@ac12)", () => {
  function buildOrderOrchestrator() {
    const defaultDelegate = mockDelegate("default", "default response");
    const orderDelegate = mockDelegate("order_agent", "order response");
    const productDelegate = mockDelegate("product_agent", "product response");

    const intentResolver = new DeterministicIntentResolver<"order" | "product" | "unknown">([
      { pattern: /訂單/, intent: { object: "order", confidence: 1.0 } },
      { pattern: /產品|搜尋/, intent: { object: "product", confidence: 1.0 } },
    ]);

    const delegates = new Map<"order" | "product" | "unknown", AgentChatDelegate>([
      ["order", orderDelegate],
      ["product", productDelegate],
    ]);

    return new AgentOrchestrator<"order" | "product" | "unknown">({
      delegate: defaultDelegate,
      delegates,
      intentResolver,
    });
  }

  it("routes order query to order delegate", async () => {
    const orchestrator = buildOrderOrchestrator();
    const result = await orchestrator.chat("查詢訂單狀態") as OrchestrationResult;

    expect(result.blocked).toBe(false);
    expect(result.content).toContain("order_agent");
  });

  it("routes product query to product delegate", async () => {
    const orchestrator = buildOrderOrchestrator();
    const result = await orchestrator.chat("搜尋產品") as OrchestrationResult;

    expect(result.blocked).toBe(false);
    expect(result.content).toContain("product_agent");
  });

  it("uses default delegate when no pattern matches", async () => {
    const orchestrator = buildOrderOrchestrator();
    const result = await orchestrator.chat("你好") as OrchestrationResult;

    expect(result.blocked).toBe(false);
    expect(result.content).toContain("default");
  });

  it("decisionTrace records delegate used", async () => {
    const orchestrator = buildOrderOrchestrator();
    const result = await orchestrator.chat("查詢訂單狀態") as OrchestrationResult;

    expect(result.decisionTrace).toBeDefined();
    expect(result.decisionTrace.delegateUsed).toBe("order");
  });
});

// ---------------------------------------------------------------------------
// @ac13 — Direct Executor
// ---------------------------------------------------------------------------

describe("Orchestration_DirectExecutor (@ac13)", () => {
  it("direct executor handles ping without LLM", async () => {
    const delegate = mockDelegate("default", "should not be called");

    const pingExecutor: BaseDirectExecutor = {
      name: "ping-executor",
      canHandle(intent: OrchestratorIntent): boolean {
        return intent.object === "ping";
      },
      async execute(_input): Promise<OrchestrationResult | null> {
        const base: NaruResult = {
          content: "pong",
          blocked: false,
          usage: { promptTokens: 0, completionTokens: 0, totalTokens: 0 },
          intent: null,
          toolCalls: [],
          timings: {},
          sessionId: null,
          traceId: null,
          trace: null,
        };
        return {
          ...base,
          orchestrationIntent: null,
          decisionTrace: {
            traceId: "test",
            phaseReached: "direct_execution",
            intentResolved: null,
            timings: { total: 0 },
            directExecutorUsed: "ping-executor",
            delegateUsed: null,
          },
          pendingConfirmation: null,
          sessionId: null,
        };
      },
    };

    const intentResolver = new DeterministicIntentResolver([
      { pattern: /^ping$/, intent: { object: "ping", confidence: 1.0 } },
    ]);

    const orchestrator = new AgentOrchestrator({
      delegate,
      intentResolver,
      directExecutors: [pingExecutor],
    });

    const result = await orchestrator.chat("ping") as OrchestrationResult;

    expect(result.content).toBe("pong");
    expect(result.decisionTrace.phaseReached).toBe("direct_execution");
    expect(result.decisionTrace.directExecutorUsed).toBe("ping-executor");
  });

  it("falls through to delegate when executor returns null", async () => {
    const delegate = mockDelegate("default", "fallthrough response");

    const nullExecutor: BaseDirectExecutor = {
      name: "null-executor",
      canHandle(_intent: OrchestratorIntent): boolean {
        return true;
      },
      async execute(_input): Promise<null> {
        return null;
      },
    };

    const orchestrator = new AgentOrchestrator({
      delegate,
      directExecutors: [nullExecutor],
    });

    const result = await orchestrator.chat("anything") as OrchestrationResult;

    expect(result.content).toContain("default");
  });
});

// ---------------------------------------------------------------------------
// @ac14 — 多步驟確認流程
// ---------------------------------------------------------------------------

describe("Orchestration_MultiStepConfirmation (@ac14)", () => {
  it("pending state stores confirmation request", async () => {
    const pendingManager = new InMemoryPendingStateManager();
    const sessionId = "confirm-test-session";

    await pendingManager.setPending(sessionId, {
      type: "delete_orders",
      payload: { all: true },
      createdAt: Date.now(),
    });

    const delegate = mockDelegate("default", "executed deletion");
    const orchestrator = new AgentOrchestrator({
      delegate,
      pendingStateManager: pendingManager,
    });

    const result = await orchestrator.chat("確認", { sessionId }) as OrchestrationResult;

    expect(result.blocked).toBe(false);
    expect(result.content).toContain("delete_orders");
    expect(result.decisionTrace.phaseReached).toBe("pending_confirmation");
  });

  it("rejection clears pending state", async () => {
    const pendingManager = new InMemoryPendingStateManager();
    const sessionId = "reject-test-session";

    await pendingManager.setPending(sessionId, {
      type: "delete_orders",
      payload: {},
      createdAt: Date.now(),
    });

    const delegate = mockDelegate("default");
    const orchestrator = new AgentOrchestrator({
      delegate,
      pendingStateManager: pendingManager,
    });

    const result = await orchestrator.chat("取消", { sessionId }) as OrchestrationResult;

    expect(result.blocked).toBe(false);
    // Pending should be cleared
    const remaining = await pendingManager.getPending(sessionId);
    expect(remaining).toBeNull();
  });

  it("override clears pending and continues normal flow", async () => {
    const pendingManager = new InMemoryPendingStateManager();
    const sessionId = "override-test-session";

    await pendingManager.setPending(sessionId, {
      type: "delete_orders",
      payload: {},
      createdAt: Date.now(),
    });

    const delegate = mockDelegate("default", "normal response");
    const orchestrator = new AgentOrchestrator({
      delegate,
      pendingStateManager: pendingManager,
    });

    // A non-confirmation, non-rejection message should override
    const result = await orchestrator.chat("完全不同的問題", { sessionId }) as OrchestrationResult;

    expect(result.blocked).toBe(false);
    // Should have continued to delegate (override clears pending and routes normally)
    const remaining = await pendingManager.getPending(sessionId);
    expect(remaining).toBeNull();
  });
});
