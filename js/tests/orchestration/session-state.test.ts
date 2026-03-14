import { describe, it, expect } from "vitest";
import { InMemorySessionStateStore } from "../../src/orchestration/session-state.js";
import { AgentOrchestrator } from "../../src/orchestration/orchestrator.js";
import type { OrchestrationResult } from "../../src/orchestration/result.js";
import { makeMockNaruResult } from "./helpers.js";

describe("InMemorySessionStateStore - AC9", () => {
  it("should store and retrieve session state", async () => {
    const store = new InMemorySessionStateStore();
    const state = {
      sessionId: "sess-1",
      lastPresentedEntities: [{ id: "1", title: "Task A" }, { id: "2", title: "Task B" }],
      metadata: { lastQuery: "list tasks" },
      updatedAt: Date.now(),
    };

    await store.save("sess-1", state);
    const retrieved = await store.get("sess-1");

    expect(retrieved).not.toBeNull();
    expect(retrieved?.lastPresentedEntities).toHaveLength(2);
    expect(retrieved?.metadata.lastQuery).toBe("list tasks");
  });

  it("should return null for unknown session", async () => {
    const store = new InMemorySessionStateStore();
    const result = await store.get("unknown-session");
    expect(result).toBeNull();
  });

  it("should clear session state", async () => {
    const store = new InMemorySessionStateStore();
    await store.save("sess-1", {
      sessionId: "sess-1",
      lastPresentedEntities: ["item"],
      metadata: {},
      updatedAt: Date.now(),
    });

    await store.clear("sess-1");
    const result = await store.get("sess-1");
    expect(result).toBeNull();
  });
});

describe("AgentOrchestrator - AC9: Session state integration", () => {
  it("should pass session state to delegate via enriched options", async () => {
    const store = new InMemorySessionStateStore();
    await store.save("sess-1", {
      sessionId: "sess-1",
      lastPresentedEntities: [{ id: "1", title: "Task A" }],
      metadata: {},
      updatedAt: Date.now(),
    });

    let receivedOptions: unknown;
    const orchestrator = new AgentOrchestrator({
      delegate: {
        chat: async (_msg, opts) => {
          receivedOptions = opts;
          return makeMockNaruResult({ content: "response", sessionId: "sess-1" });
        },
      },
      sessionStateStore: store,
    });

    await orchestrator.chat("第一個任務", { sessionId: "sess-1" });

    // The options should be enriched with sessionState
    expect(receivedOptions).toBeDefined();
    expect((receivedOptions as Record<string, unknown>).sessionState).toBeDefined();
    const sessionState = (receivedOptions as Record<string, unknown>).sessionState as Record<string, unknown>;
    expect((sessionState.lastPresentedEntities as unknown[]).length).toBe(1);
  });

  it("should continue without session state enrichment when no state exists", async () => {
    const store = new InMemorySessionStateStore();
    let receivedOptions: unknown;

    const orchestrator = new AgentOrchestrator({
      delegate: {
        chat: async (_msg, opts) => {
          receivedOptions = opts;
          return makeMockNaruResult({ content: "response" });
        },
      },
      sessionStateStore: store,
    });

    await orchestrator.chat("hello", { sessionId: "fresh-session" });

    // Options should be passed as-is without sessionState enrichment
    expect((receivedOptions as Record<string, unknown>)?.sessionState).toBeUndefined();
  });

  it("should save updated session state after delegate response", async () => {
    const store = new InMemorySessionStateStore();

    const orchestrator = new AgentOrchestrator({
      delegate: {
        chat: async () => makeMockNaruResult({ content: "Here are your tasks: Task A, Task B", sessionId: "sess-1" }),
      },
      sessionStateStore: store,
    });

    await orchestrator.chat("list tasks", { sessionId: "sess-1" });

    // The delegate returned a sessionId so the orchestrator should have saved state
    const state = await store.get("sess-1");
    expect(state).not.toBeNull();
    expect(state?.sessionId).toBe("sess-1");
    expect(typeof state?.updatedAt).toBe("number");
  });
});
