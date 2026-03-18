import { describe, it, expect, vi } from "vitest";
import { AgentHandoffLoop } from "../../src/orchestration/handoff.js";
import type { AgentChatDelegate } from "../../src/orchestration/orchestrator.js";
import type { HandoffRequest } from "../../src/types.js";
import { makeMockNaruResult } from "./helpers.js";

function makeMockDelegate(
  content: string,
  handoff?: HandoffRequest | null,
): AgentChatDelegate {
  return {
    chat: vi.fn().mockResolvedValue(
      makeMockNaruResult({ content, handoff: handoff ?? null }),
    ),
  };
}

describe("AgentHandoffLoop", () => {
  describe("single hop", () => {
    it("A hands off to B, B returns normally", async () => {
      const agentA = makeMockDelegate("", { target: "b", reason: "billing" });
      const agentB = makeMockDelegate("billing response");

      const loop = new AgentHandoffLoop(
        new Map([["a", agentA], ["b", agentB]]),
        "a",
      );
      const result = await loop.chat("billing question");

      expect(agentA.chat).toHaveBeenCalledOnce();
      expect(agentB.chat).toHaveBeenCalledOnce();
      expect(result.content).toBe("billing response");
    });

    it("uses custom handoff message", async () => {
      const agentA = makeMockDelegate("", {
        target: "b",
        message: "handle billing",
      });
      const agentB = makeMockDelegate("done");

      const loop = new AgentHandoffLoop(
        new Map([["a", agentA], ["b", agentB]]),
        "a",
      );
      await loop.chat("original");

      expect(agentB.chat).toHaveBeenCalledWith("handle billing", undefined);
    });

    it("uses original message when handoff has no custom message", async () => {
      const agentA = makeMockDelegate("", { target: "b" });
      const agentB = makeMockDelegate("done");

      const loop = new AgentHandoffLoop(
        new Map([["a", agentA], ["b", agentB]]),
        "a",
      );
      await loop.chat("original");

      expect(agentB.chat).toHaveBeenCalledWith("original", undefined);
    });
  });

  describe("chain", () => {
    it("follows A → B → C chain", async () => {
      const agentA = makeMockDelegate("", { target: "b" });
      const agentB = makeMockDelegate("", { target: "c" });
      const agentC = makeMockDelegate("final answer");

      const loop = new AgentHandoffLoop(
        new Map([["a", agentA], ["b", agentB], ["c", agentC]]),
        "a",
      );
      const result = await loop.chat("question");

      expect(result.content).toBe("final answer");
      expect(agentA.chat).toHaveBeenCalledOnce();
      expect(agentB.chat).toHaveBeenCalledOnce();
      expect(agentC.chat).toHaveBeenCalledOnce();
    });
  });

  describe("max limit", () => {
    it("stops after maxHandoffs iterations", async () => {
      const agentA = makeMockDelegate("loop-a", { target: "b" });
      const agentB = makeMockDelegate("loop-b", { target: "a" });

      const loop = new AgentHandoffLoop(
        new Map([["a", agentA], ["b", agentB]]),
        "a",
        3,
      );
      const result = await loop.chat("question");

      expect(result).not.toBeNull();
      const totalCalls =
        (agentA.chat as ReturnType<typeof vi.fn>).mock.calls.length +
        (agentB.chat as ReturnType<typeof vi.fn>).mock.calls.length;
      expect(totalCalls).toBe(4); // max_handoffs + 1
    });
  });

  describe("no handoff", () => {
    it("returns directly when no handoff", async () => {
      const agent = makeMockDelegate("direct answer");
      const loop = new AgentHandoffLoop(new Map([["main", agent]]), "main");
      const result = await loop.chat("question");

      expect(result.content).toBe("direct answer");
      expect(result.handoff).toBeNull();
      expect(agent.chat).toHaveBeenCalledOnce();
    });
  });

  describe("unknown agent", () => {
    it("throws on unknown handoff target", async () => {
      const agentA = makeMockDelegate("", { target: "nonexistent" });
      const loop = new AgentHandoffLoop(new Map([["a", agentA]]), "a");

      await expect(loop.chat("question")).rejects.toThrow(
        "Unknown agent: nonexistent",
      );
    });

    it("throws on unknown entry agent", () => {
      const agent = makeMockDelegate("x");
      expect(
        () => new AgentHandoffLoop(new Map([["a", agent]]), "bad"),
      ).toThrow("Entry agent 'bad' not found");
    });
  });

  describe("empty agents", () => {
    it("throws on empty agents map", () => {
      expect(() => new AgentHandoffLoop(new Map(), "a")).toThrow(
        "at least one agent",
      );
    });
  });

  describe("options forwarding", () => {
    it("forwards options through handoff chain", async () => {
      const agentA = makeMockDelegate("", { target: "b" });
      const agentB = makeMockDelegate("done");

      const loop = new AgentHandoffLoop(
        new Map([["a", agentA], ["b", agentB]]),
        "a",
      );
      await loop.chat("msg", { userId: "u1", sessionId: "s1" });

      expect(agentA.chat).toHaveBeenCalledWith("msg", {
        userId: "u1",
        sessionId: "s1",
      });
      expect(agentB.chat).toHaveBeenCalledWith("msg", {
        userId: "u1",
        sessionId: "s1",
      });
    });
  });

  describe("name", () => {
    it("uses custom name", () => {
      const loop = new AgentHandoffLoop(
        new Map([["a", makeMockDelegate("x")]]),
        "a",
        5,
        "my_loop",
      );
      expect(loop.name).toBe("my_loop");
    });

    it("defaults to 'handoff_loop'", () => {
      const loop = new AgentHandoffLoop(
        new Map([["a", makeMockDelegate("x")]]),
        "a",
      );
      expect(loop.name).toBe("handoff_loop");
    });
  });
});
