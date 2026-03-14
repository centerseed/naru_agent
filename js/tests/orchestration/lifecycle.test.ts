import { describe, it, expect, vi } from "vitest";
import { AgentOrchestrator } from "../../src/orchestration/orchestrator.js";
import type { OrchestrationResult } from "../../src/orchestration/result.js";
import { makeMockNaruResult } from "./helpers.js";

describe("Lifecycle Hooks - AC13", () => {
  it("should call beforeMessage before processing", async () => {
    const beforeMessage = vi.fn();
    const orchestrator = new AgentOrchestrator({
      delegate: { chat: async () => makeMockNaruResult({ content: "response" }) },
      lifecycleHooks: { beforeMessage },
    });

    await orchestrator.chat("hello", { userId: "user-1" });

    expect(beforeMessage).toHaveBeenCalledOnce();
    expect(beforeMessage).toHaveBeenCalledWith("hello", { userId: "user-1" });
  });

  it("should call afterMessage with the result", async () => {
    const afterMessage = vi.fn();
    const orchestrator = new AgentOrchestrator({
      delegate: { chat: async () => makeMockNaruResult({ content: "the response" }) },
      lifecycleHooks: { afterMessage },
    });

    await orchestrator.chat("test");

    expect(afterMessage).toHaveBeenCalledOnce();
    const calledWith = afterMessage.mock.calls[0][0] as OrchestrationResult;
    expect(calledWith.content).toBe("the response");
    expect(calledWith.decisionTrace).toBeDefined();
  });

  it("should call onError when delegate throws", async () => {
    const onError = vi.fn();
    const orchestrator = new AgentOrchestrator({
      delegate: {
        chat: async () => {
          throw new Error("delegate error");
        },
      },
      lifecycleHooks: { onError },
    });

    await expect(orchestrator.chat("test")).rejects.toThrow("delegate error");
    expect(onError).toHaveBeenCalledOnce();
    expect(onError.mock.calls[0][0]).toBeInstanceOf(Error);
  });

  it("should not rethrow hook errors — hooks do not affect main flow", async () => {
    const beforeMessage = vi.fn().mockRejectedValue(new Error("hook error"));
    const orchestrator = new AgentOrchestrator({
      delegate: { chat: async () => makeMockNaruResult({ content: "main response" }) },
      lifecycleHooks: { beforeMessage },
    });

    // Should not throw even though beforeMessage throws
    const result = await orchestrator.chat("test") as OrchestrationResult;
    expect(result.content).toBe("main response");
  });

  it("should call beforeMessage before delegate and afterMessage after", async () => {
    const callOrder: string[] = [];

    const orchestrator = new AgentOrchestrator({
      delegate: {
        chat: async () => {
          callOrder.push("delegate");
          return makeMockNaruResult({ content: "response" });
        },
      },
      lifecycleHooks: {
        beforeMessage: async () => { callOrder.push("before"); },
        afterMessage: async () => { callOrder.push("after"); },
      },
    });

    await orchestrator.chat("message");
    expect(callOrder).toEqual(["before", "delegate", "after"]);
  });
});
