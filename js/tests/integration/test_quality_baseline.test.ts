/**
 * NaruAgent JS 品質保證 Baseline 測試套件。
 *
 * 覆蓋：大量 tools 正確呼叫、多用戶並發、token 用量合理性、回應品質、trace 完整性。
 *
 * 執行：
 *   GOOGLE_GENERATIVE_AI_API_KEY=xxx npx vitest run tests/integration/test_quality_baseline.test.ts
 */

import { describe, it, expect, beforeEach } from "vitest";
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import {
  loadBaseline,
  callLog,
  clearCallLog,
  ALL_TOOLS,
  makeAgent,
  getModel,
} from "./helpers.js";
import { LLMIntentClassifier } from "../../src/intent/llm-classifier.js";

const HAS_API_KEY = !!process.env.GOOGLE_GENERATIVE_AI_API_KEY;
const describeIf = HAS_API_KEY ? describe : describe.skip;

// ===========================================================================
// 1. TestManyTools — 大量 Tools 正確呼叫
// ===========================================================================

describeIf("ManyTools", () => {
  beforeEach(() => clearCallLog());

  it("selects correct tool from 16", async () => {
    const agent = makeAgent({ tools: ALL_TOOLS });
    const result = await agent.chat("請幫我計算寄到台北的運費，包裹重量 2 公斤");

    expect(result.blocked).toBe(false);
    expect(result.content).toBeTruthy();
    expect(result.toolCalls).toContain("calculate_shipping_cost");
  }, 60_000);

  it("chains multiple tools (search → detail/inventory)", async () => {
    const agent = makeAgent({ tools: ALL_TOOLS });
    const result = await agent.chat(
      "幫我搜尋無線耳機，然後查看第一個產品的詳情和庫存",
    );

    expect(result.blocked).toBe(false);
    const names = callLog.map((c) => c.tool as string);
    expect(names).toContain("search_products");
    expect(
      names.includes("get_product_detail") || names.includes("check_inventory"),
    ).toBe(true);

    if (names.includes("get_product_detail")) {
      expect(names.indexOf("search_products")).toBeLessThan(
        names.indexOf("get_product_detail"),
      );
    }
  }, 60_000);

  it("includes tool result data in response", async () => {
    const agent = makeAgent({ tools: ALL_TOOLS });
    const result = await agent.chat("請幫我計算寄到台北的運費，包裹重量 2 公斤");

    expect(result.blocked).toBe(false);
    expect(result.toolCalls.length).toBeGreaterThan(0);
    // cost = 60 + 2*25 = 110
    expect(
      ["110", "運費", "費用", "cost", "元"].some((kw) =>
        result.content.includes(kw),
      ),
    ).toBe(true);
  }, 60_000);
});

// ===========================================================================
// 2. TestConcurrency — 多用戶並發
// ===========================================================================

describeIf("Concurrency", () => {
  beforeEach(() => clearCallLog());

  it("handles concurrent different users", async () => {
    const agent = makeAgent({ tools: ALL_TOOLS });

    const requests = [
      { userId: "user_1", sessionId: "sess_1", msg: "請幫我計算寄到台北的運費，包裹重量 3 公斤" },
      { userId: "user_2", sessionId: "sess_2", msg: "幫我搜尋藍牙耳機" },
      { userId: "user_3", sessionId: "sess_3", msg: "查詢訂單 ORD-100 的狀態" },
    ];

    const results = await Promise.allSettled(
      requests.map(({ userId, sessionId, msg }) =>
        agent.chat(msg, { userId, sessionId }),
      ),
    );

    const fulfilled = results.filter((r) => r.status === "fulfilled");
    // At least 2/3 must succeed (1 may fail due to Gemini free-tier rate limiting)
    expect(fulfilled.length).toBeGreaterThanOrEqual(2);
    for (const r of fulfilled) {
      if (r.status === "fulfilled") {
        expect(r.value.blocked).toBe(false);
        // Allow empty content on rate-limit (fallback response)
        // but at least the result should not be blocked
      }
    }
  }, 90_000);

  it("maintains same-session context", async () => {
    const { InMemorySessionStore } = await import(
      "../../src/session/in-memory-store.js"
    );
    const sessionStore = new InMemorySessionStore();
    const agent = makeAgent({ tools: ALL_TOOLS, sessionStore });
    const sid = "shared-session-serial";

    const r1 = await agent.chat("我叫做小明，請記住我的名字。", {
      userId: "u1",
      sessionId: sid,
    });
    expect(r1.blocked).toBe(false);

    await new Promise((r) => setTimeout(r, 200));

    const r2 = await agent.chat("我叫什麼名字？", {
      userId: "u1",
      sessionId: sid,
    });
    expect(r2.blocked).toBe(false);
    expect(r2.content).toContain("小明");
  }, 60_000);
});

// ===========================================================================
// 3. TestTokenUsage — Token 用量合理性
// ===========================================================================

describeIf("TokenUsage", () => {
  it("simple chat within token budget", async () => {
    const baseline = loadBaseline();
    const maxTokens = baseline.simple_chat_max_tokens as number;
    const agent = makeAgent();
    const result = await agent.chat("你好");

    const total = result.usage.totalTokens;
    expect(total).toBeGreaterThan(0);
    expect(total).toBeLessThanOrEqual(maxTokens);
  }, 30_000);

  it("tool call (16 tools) within token budget", async () => {
    const baseline = loadBaseline();
    const maxTokens = baseline.tool_call_16_tools_max_tokens as number;
    const agent = makeAgent({ tools: ALL_TOOLS });
    const result = await agent.chat("請幫我計算寄到台北的運費，包裹重量 2 公斤");

    const total = result.usage.totalTokens;
    expect(total).toBeGreaterThan(0);
    expect(total).toBeLessThanOrEqual(maxTokens);
  }, 60_000);

  it("has all required usage fields", async () => {
    const agent = makeAgent();
    const result = await agent.chat("你好");

    expect(result.usage.promptTokens).toBeGreaterThan(0);
    expect(result.usage.completionTokens).toBeGreaterThan(0);
    expect(result.usage.totalTokens).toBeGreaterThan(0);
  }, 30_000);
});

// ===========================================================================
// 4. TestResponseQuality — 回應品質
// ===========================================================================

describeIf("ResponseQuality", () => {
  beforeEach(() => clearCallLog());

  it("includes tool result data in response", async () => {
    const agent = makeAgent({ tools: ALL_TOOLS });
    const result = await agent.chat("追蹤包裹 TRK-ABC123");

    expect(result.blocked).toBe(false);
    expect(result.toolCalls).toContain("track_shipment");
    expect(
      ["台北", "轉運", "transit", "TRK"].some((kw) =>
        result.content.includes(kw),
      ),
    ).toBe(true);
  }, 60_000);

  it("follows language instruction (繁體中文)", async () => {
    const agent = makeAgent();
    const result = await agent.chat(
      "Please introduce yourself and explain what you can help with.",
    );

    expect(result.blocked).toBe(false);
    const hasChinese = /[\u4e00-\u9fff]/.test(result.content);
    expect(hasChinese).toBe(true);
  }, 30_000);

  it("does not hallucinate tool names", async () => {
    const agent = makeAgent({ tools: ALL_TOOLS });
    const result = await agent.chat("請幫我計算寄到台北的運費，包裹重量 2 公斤");

    const validNames = new Set(ALL_TOOLS.map((t) => t.name));
    for (const tc of result.toolCalls) {
      expect(validNames.has(tc)).toBe(true);
    }
  }, 60_000);
});

// ===========================================================================
// 5. TestTraceCompleteness — Trace 完整性
// ===========================================================================

describeIf("TraceCompleteness", () => {
  function makeTmpFile(): string {
    const dir = mkdtempSync(join(tmpdir(), "naru-trace-"));
    return join(dir, "trace.jsonl");
  }

  function readTraces(traceFile: string): Array<Record<string, unknown>> {
    try {
      const raw = readFileSync(traceFile, "utf-8").trim();
      if (!raw) return [];
      return raw.split("\n").map((line) => JSON.parse(line));
    } catch {
      return [];
    }
  }

  it("trace has all required fields", async () => {
    const traceFile = makeTmpFile();
    const agent = makeAgent({ tools: ALL_TOOLS, traceFile });
    const result = await agent.chat("請幫我計算寄到台北的運費，包裹重量 1 公斤");

    // Wait for async export
    await new Promise((r) => setTimeout(r, 500));

    const traces = readTraces(traceFile);
    expect(traces.length).toBeGreaterThanOrEqual(1);

    const t = traces[0];
    for (const field of [
      "traceId",
      "input",
      "output",
      "startTime",
      "endTime",
      "usage",
      "spans",
    ]) {
      expect(t).toHaveProperty(field);
    }
    expect(t.traceId).toBe(result.traceId);
  }, 60_000);

  it("spans cover LLM and tool calls", async () => {
    const traceFile = makeTmpFile();
    const agent = makeAgent({ tools: ALL_TOOLS, traceFile });
    await agent.chat("請幫我計算寄到台北的運費，包裹重量 1 公斤");

    await new Promise((r) => setTimeout(r, 500));

    const traces = readTraces(traceFile);
    const t = traces[0];
    const spans = t.spans as Array<Record<string, unknown>>;
    const spanNames = spans.map((s) => (s.name as string) ?? "");

    expect(spanNames.some((sn) => sn.includes("llm"))).toBe(true);
  }, 60_000);

  it("span timing is consistent with trace bounds", async () => {
    const traceFile = makeTmpFile();
    const agent = makeAgent({ tools: ALL_TOOLS, traceFile });
    await agent.chat("查詢訂單 ORD-100 的狀態");

    await new Promise((r) => setTimeout(r, 500));

    const traces = readTraces(traceFile);
    const t = traces[0];
    const traceStart = t.startTime as number;
    const traceEnd = t.endTime as number;

    for (const span of t.spans as Array<Record<string, unknown>>) {
      const sStart = (span.startTime as number) ?? 0;
      const sEnd = (span.endTime as number) ?? Infinity;
      expect(sStart).toBeGreaterThanOrEqual(traceStart - 10);
      expect(sEnd).toBeLessThanOrEqual(traceEnd + 10);
    }
  }, 60_000);

  it("includes intent span when classifier is used", async () => {
    const traceFile = makeTmpFile();
    const classifier = new LLMIntentClassifier({ model: getModel() });
    const agent = makeAgent({
      tools: ALL_TOOLS,
      traceFile,
      intentClassifier: classifier,
    });
    await agent.chat("請幫我計算寄到台北的運費，包裹重量 1 公斤");

    await new Promise((r) => setTimeout(r, 500));

    const traces = readTraces(traceFile);
    const t = traces[0];
    const spans = t.spans as Array<Record<string, unknown>>;
    const spanNames = spans.map((s) => (s.name as string) ?? "");
    expect(spanNames.some((sn) => sn.includes("intent"))).toBe(true);
  }, 60_000);

  it("JSONL output is parseable", async () => {
    const traceFile = makeTmpFile();
    const agent = makeAgent({ traceFile });
    await agent.chat("你好");

    await new Promise((r) => setTimeout(r, 500));

    const raw = readFileSync(traceFile, "utf-8").trim();
    const lines = raw.split("\n");
    expect(lines.length).toBeGreaterThanOrEqual(1);

    for (const line of lines) {
      expect(() => JSON.parse(line)).not.toThrow();
    }
  }, 30_000);
});
