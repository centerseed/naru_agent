import { describe, it, expect, vi } from "vitest";
import {
  DeterministicIntentResolver,
  LLMFallbackIntentResolver,
} from "../../src/orchestration/intent.js";

describe("DeterministicIntentResolver - AC3", () => {
  const resolver = new DeterministicIntentResolver([
    { pattern: /^整理/, intent: { object: "reorganize", confidence: 1.0 } },
    { pattern: /你好|嗨/, intent: { object: "greeting", confidence: 0.9 } },
  ]);

  it("should match first pattern and return correct intent", async () => {
    const result = await resolver.resolve({ message: "整理一下" });
    expect(result.object).toBe("reorganize");
    expect(result.confidence).toBe(1.0);
  });

  it("should return unknown with confidence 0 when no pattern matches", async () => {
    const result = await resolver.resolve({ message: "今天天氣如何" });
    expect(result.object).toBe("unknown");
    expect(result.confidence).toBe(0);
  });

  it("should match greeting pattern in middle of string", async () => {
    const result = await resolver.resolve({ message: "你好，請問" });
    expect(result.object).toBe("greeting");
    expect(result.confidence).toBe(0.9);
  });

  it("should stop at first matching pattern (not check subsequent ones)", async () => {
    // This resolver has reorganize before greeting
    const mixedResolver = new DeterministicIntentResolver([
      { pattern: /整理/, intent: { object: "reorganize", confidence: 1.0 } },
      { pattern: /整理/, intent: { object: "other", confidence: 0.5 } },
    ]);
    const result = await mixedResolver.resolve({ message: "整理文件" });
    expect(result.object).toBe("reorganize");
    expect(result.confidence).toBe(1.0);
  });

  it("should handle empty pattern list returning unknown", async () => {
    const emptyResolver = new DeterministicIntentResolver([]);
    const result = await emptyResolver.resolve({ message: "anything" });
    expect(result.object).toBe("unknown");
    expect(result.confidence).toBe(0);
  });
});

describe("LLMFallbackIntentResolver - AC4", () => {
  it("should not call LLM when deterministic returns non-unknown intent", async () => {
    const primary = new DeterministicIntentResolver([
      { pattern: /整理/, intent: { object: "reorganize", confidence: 1.0 } },
    ]);
    const fallbackAgent = { chat: vi.fn() };
    const resolver = new LLMFallbackIntentResolver({ primary, fallbackAgent });

    const result = await resolver.resolve({ message: "整理一下" });

    expect(fallbackAgent.chat).not.toHaveBeenCalled();
    expect(result.object).toBe("reorganize");
    expect(result.confidence).toBe(1.0);
  });

  it("should call LLM fallback when deterministic returns unknown", async () => {
    const primary = new DeterministicIntentResolver([]);
    const fallbackAgent = {
      chat: vi.fn().mockResolvedValue({
        content: JSON.stringify({ object: "query", confidence: 0.8 }),
      }),
    };
    const resolver = new LLMFallbackIntentResolver({ primary, fallbackAgent });

    const result = await resolver.resolve({ message: "今天天氣如何" });

    expect(fallbackAgent.chat).toHaveBeenCalledOnce();
    expect(result.object).toBe("query");
    expect(result.confidence).toBe(0.8);
  });

  it("should use custom parseResponse when provided", async () => {
    const primary = new DeterministicIntentResolver([]);
    const fallbackAgent = {
      chat: vi.fn().mockResolvedValue({ content: "action:0.95" }),
    };
    const parseResponse = (content: string) => {
      const [obj, conf] = content.split(":");
      return { object: obj, confidence: parseFloat(conf) };
    };
    const resolver = new LLMFallbackIntentResolver({
      primary,
      fallbackAgent,
      parseResponse,
    });

    const result = await resolver.resolve({ message: "do something" });
    expect(result.object).toBe("action");
    expect(result.confidence).toBe(0.95);
  });

  it("should return unknown on LLM parse error", async () => {
    const primary = new DeterministicIntentResolver([]);
    const fallbackAgent = {
      chat: vi.fn().mockResolvedValue({ content: "invalid json {{" }),
    };
    const resolver = new LLMFallbackIntentResolver({ primary, fallbackAgent });

    const result = await resolver.resolve({ message: "test" });
    expect(result.object).toBe("unknown");
    expect(result.confidence).toBe(0);
  });
});
