import { describe, it, expect, vi } from "vitest";
import { AgentFanout } from "../../src/orchestration/fanout.js";
import type { AgentChatDelegate } from "../../src/orchestration/orchestrator.js";
import type { NaruResult } from "../../src/types.js";
import { makeMockNaruResult } from "./helpers.js";

function makeMockDelegate(content: string): AgentChatDelegate {
  return {
    chat: vi.fn().mockResolvedValue(makeMockNaruResult({ content })),
  };
}

describe("AgentFanout", () => {
  describe("parallel execution", () => {
    it("calls all agents with the same message", async () => {
      const agents = [
        makeMockDelegate("a"),
        makeMockDelegate("b"),
        makeMockDelegate("c"),
      ];
      const fanout = new AgentFanout(agents);
      await fanout.chat("hello");

      for (const agent of agents) {
        expect(agent.chat).toHaveBeenCalledWith("hello", undefined);
      }
    });

    it("forwards options to all agents", async () => {
      const agents = [makeMockDelegate("x"), makeMockDelegate("y")];
      const fanout = new AgentFanout(agents);
      await fanout.chat("query", { userId: "u1", sessionId: "s1" });

      for (const agent of agents) {
        expect(agent.chat).toHaveBeenCalledWith("query", {
          userId: "u1",
          sessionId: "s1",
        });
      }
    });
  });

  describe("default merge", () => {
    it("joins content with separator", async () => {
      const agents = [makeMockDelegate("result A"), makeMockDelegate("result B")];
      const fanout = new AgentFanout(agents);
      const result = await fanout.chat("query");

      expect(result.content).toBe("result A\n\n---\n\nresult B");
    });

    it("filters empty content", async () => {
      const agents = [
        makeMockDelegate("result A"),
        makeMockDelegate(""),
        makeMockDelegate("result C"),
      ];
      const fanout = new AgentFanout(agents);
      const result = await fanout.chat("query");

      expect(result.content).toBe("result A\n\n---\n\nresult C");
    });
  });

  describe("custom merge", () => {
    it("uses custom merge function", async () => {
      const agents = [makeMockDelegate("a"), makeMockDelegate("b")];
      const fanout = new AgentFanout(agents, {
        merge: (results: NaruResult[]) =>
          makeMockNaruResult({
            content: results.map((r) => r.content).join("+"),
          }),
      });
      const result = await fanout.chat("query");

      expect(result.content).toBe("a+b");
    });
  });

  describe("single agent", () => {
    it("acts as passthrough", async () => {
      const agent = makeMockDelegate("only result");
      const fanout = new AgentFanout([agent]);
      const result = await fanout.chat("query");

      expect(result.content).toBe("only result");
    });
  });

  describe("preserves order", () => {
    it("results are in original agent order", async () => {
      // Simulate agents resolving in reverse order
      const slowAgent: AgentChatDelegate = {
        chat: vi.fn().mockImplementation(
          () =>
            new Promise((resolve) =>
              setTimeout(() => resolve(makeMockNaruResult({ content: "slow" })), 50),
            ),
        ),
      };
      const fastAgent: AgentChatDelegate = {
        chat: vi.fn().mockResolvedValue(makeMockNaruResult({ content: "fast" })),
      };

      const fanout = new AgentFanout([slowAgent, fastAgent]);
      const result = await fanout.chat("query");

      // Promise.all preserves order regardless of resolution time
      expect(result.content).toBe("slow\n\n---\n\nfast");
    });
  });

  describe("empty agents", () => {
    it("throws on empty agents", () => {
      expect(() => new AgentFanout([])).toThrow("at least one agent");
    });
  });

  describe("name", () => {
    it("uses custom name", () => {
      const fanout = new AgentFanout([makeMockDelegate("x")], {
        name: "my_fanout",
      });
      expect(fanout.name).toBe("my_fanout");
    });

    it("defaults to 'fanout'", () => {
      const fanout = new AgentFanout([makeMockDelegate("x")]);
      expect(fanout.name).toBe("fanout");
    });
  });
});
