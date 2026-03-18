import { describe, it, expect, vi } from "vitest";
import { AgentPipeline } from "../../src/orchestration/pipeline.js";
import type { AgentChatDelegate } from "../../src/orchestration/orchestrator.js";
import { makeMockNaruResult } from "./helpers.js";

function makeMockDelegate(content: string): AgentChatDelegate {
  return {
    chat: vi.fn().mockResolvedValue(makeMockNaruResult({ content })),
  };
}

function makeEchoDelegate(): AgentChatDelegate {
  return {
    chat: vi.fn().mockImplementation(async (msg: string) =>
      makeMockNaruResult({ content: `[processed] ${msg}` }),
    ),
  };
}

describe("AgentPipeline", () => {
  describe("two stages", () => {
    it("second stage receives first stage's output", async () => {
      const stageA = makeMockDelegate("research result");
      const stageB = makeMockDelegate("summary");

      const pipeline = new AgentPipeline([stageA, stageB]);
      const result = await pipeline.chat("original question");

      expect(stageA.chat).toHaveBeenCalledWith("original question", undefined);
      expect(stageB.chat).toHaveBeenCalledWith("research result", undefined);
      expect(result.content).toBe("summary");
    });

    it("chains three stages", async () => {
      const stageA = makeMockDelegate("step1");
      const stageB = makeMockDelegate("step2");
      const stageC = makeMockDelegate("step3");

      const pipeline = new AgentPipeline([stageA, stageB, stageC]);
      const result = await pipeline.chat("input");

      expect(stageB.chat).toHaveBeenCalledWith("step1", undefined);
      expect(stageC.chat).toHaveBeenCalledWith("step2", undefined);
      expect(result.content).toBe("step3");
    });
  });

  describe("single stage", () => {
    it("acts as passthrough", async () => {
      const delegate = makeEchoDelegate();
      const pipeline = new AgentPipeline([delegate]);
      const result = await pipeline.chat("hello");

      expect(result.content).toBe("[processed] hello");
    });
  });

  describe("empty stages", () => {
    it("throws on empty stages", () => {
      expect(() => new AgentPipeline([])).toThrow("at least one stage");
    });
  });

  describe("options forwarding", () => {
    it("forwards ChatOptions to every stage", async () => {
      const stageA = makeMockDelegate("a");
      const stageB = makeMockDelegate("b");

      const pipeline = new AgentPipeline([stageA, stageB]);
      await pipeline.chat("msg", { userId: "u1", sessionId: "s1" });

      expect(stageA.chat).toHaveBeenCalledWith("msg", { userId: "u1", sessionId: "s1" });
      expect(stageB.chat).toHaveBeenCalledWith("a", { userId: "u1", sessionId: "s1" });
    });
  });

  describe("returns last result", () => {
    it("returns the full NaruResult from last stage", async () => {
      const stageA = makeMockDelegate("a");
      const lastResult = makeMockNaruResult({ content: "final", sessionId: "s1" });
      const stageB: AgentChatDelegate = {
        chat: vi.fn().mockResolvedValue(lastResult),
      };

      const pipeline = new AgentPipeline([stageA, stageB]);
      const result = await pipeline.chat("input");

      expect(result).toBe(lastResult);
      expect(result.sessionId).toBe("s1");
    });
  });

  describe("name", () => {
    it("uses custom name", () => {
      const pipeline = new AgentPipeline([makeMockDelegate("x")], "my_pipeline");
      expect(pipeline.name).toBe("my_pipeline");
    });

    it("defaults to 'pipeline'", () => {
      const pipeline = new AgentPipeline([makeMockDelegate("x")]);
      expect(pipeline.name).toBe("pipeline");
    });
  });
});
