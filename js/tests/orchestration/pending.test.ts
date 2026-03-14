import { describe, it, expect } from "vitest";
import {
  InMemoryPendingStateManager,
  classifyConfirmationDisposition,
} from "../../src/orchestration/pending.js";
import { AgentOrchestrator } from "../../src/orchestration/orchestrator.js";
import type { OrchestrationResult } from "../../src/orchestration/result.js";
import { makeMockNaruResult } from "./helpers.js";

describe("classifyConfirmationDisposition - AC7", () => {
  it("should classify confirmation messages", () => {
    expect(classifyConfirmationDisposition("好")).toBe("confirm");
    expect(classifyConfirmationDisposition("確認")).toBe("confirm");
    expect(classifyConfirmationDisposition("對")).toBe("confirm");
    expect(classifyConfirmationDisposition("yes")).toBe("confirm");
    expect(classifyConfirmationDisposition("ok")).toBe("confirm");
  });

  it("should classify rejection messages", () => {
    expect(classifyConfirmationDisposition("不要")).toBe("reject");
    expect(classifyConfirmationDisposition("取消")).toBe("reject");
    expect(classifyConfirmationDisposition("no")).toBe("reject");
    expect(classifyConfirmationDisposition("cancel")).toBe("reject");
  });

  it("should classify unrelated messages as override", () => {
    expect(classifyConfirmationDisposition("幫我查一下天氣")).toBe("override");
    expect(classifyConfirmationDisposition("改成明天")).toBe("override");
    expect(classifyConfirmationDisposition("隨便")).toBe("override");
  });

  it("should be case-insensitive for english keywords", () => {
    expect(classifyConfirmationDisposition("YES")).toBe("confirm");
    expect(classifyConfirmationDisposition("No")).toBe("reject");
  });
});

describe("InMemoryPendingStateManager - AC6", () => {
  it("should store and retrieve pending state", async () => {
    const manager = new InMemoryPendingStateManager();
    await manager.setPending("sess-1", {
      type: "adjust_tags",
      payload: { tags: ["work", "urgent"] },
      createdAt: Date.now(),
    });

    const pending = await manager.getPending("sess-1");
    expect(pending).not.toBeNull();
    expect(pending?.type).toBe("adjust_tags");
    expect(pending?.payload.tags).toEqual(["work", "urgent"]);
  });

  it("should return null for non-existent session", async () => {
    const manager = new InMemoryPendingStateManager();
    const pending = await manager.getPending("nonexistent");
    expect(pending).toBeNull();
  });

  it("should clear pending state after retrieval", async () => {
    const manager = new InMemoryPendingStateManager();
    await manager.setPending("sess-1", {
      type: "delete_task",
      payload: { taskId: "123" },
      createdAt: Date.now(),
    });

    await manager.clearPending("sess-1");
    const pending = await manager.getPending("sess-1");
    expect(pending).toBeNull();
  });
});

describe("AgentOrchestrator - AC6: Pending confirmation flow", () => {
  it("should intercept pending confirmation and set phaseReached to pending_confirmation", async () => {
    const pendingManager = new InMemoryPendingStateManager();
    await pendingManager.setPending("sess-1", {
      type: "adjust_tags",
      payload: { tags: ["work"] },
      createdAt: Date.now(),
    });

    const orchestrator = new AgentOrchestrator({
      delegate: { chat: async () => makeMockNaruResult({ content: "delegate response" }) },
      pendingStateManager: pendingManager,
    });

    const result = await orchestrator.chat("確認", { sessionId: "sess-1" }) as OrchestrationResult;

    expect(result.decisionTrace.phaseReached).toBe("pending_confirmation");
  });

  it("should clear pending state after confirmation", async () => {
    const pendingManager = new InMemoryPendingStateManager();
    await pendingManager.setPending("sess-1", {
      type: "delete_task",
      payload: {},
      createdAt: Date.now(),
    });

    const orchestrator = new AgentOrchestrator({
      delegate: { chat: async () => makeMockNaruResult({ content: "response" }) },
      pendingStateManager: pendingManager,
    });

    await orchestrator.chat("好", { sessionId: "sess-1" });

    const remaining = await pendingManager.getPending("sess-1");
    expect(remaining).toBeNull();
  });

  it("should continue normal flow when disposition is override", async () => {
    const pendingManager = new InMemoryPendingStateManager();
    await pendingManager.setPending("sess-1", {
      type: "adjust_tags",
      payload: {},
      createdAt: Date.now(),
    });

    let delegateCalled = false;
    const orchestrator = new AgentOrchestrator({
      delegate: {
        chat: async () => {
          delegateCalled = true;
          return makeMockNaruResult({ content: "delegate called" });
        },
      },
      pendingStateManager: pendingManager,
    });

    const result = await orchestrator.chat("查一下天氣", { sessionId: "sess-1" }) as OrchestrationResult;

    expect(delegateCalled).toBe(true);
    expect(result.decisionTrace.phaseReached).toBe("delegate");
    // pending should be cleared on override
    const remaining = await pendingManager.getPending("sess-1");
    expect(remaining).toBeNull();
  });
});
