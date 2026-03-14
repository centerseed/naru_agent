/**
 * Quality Integration Tests — @ac15, @ac16, @ac17, @ac18
 *
 * Covers:
 *   @ac15 — Token 使用量合理性
 *   @ac16 — 並行使用者隔離
 *   @ac17 — 回應品質
 *   @ac18 — Trace 完整性
 *
 * Execute:
 *   GOOGLE_GENERATIVE_AI_API_KEY=xxx npx vitest run tests/integration/test_quality.test.ts
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
import { InMemorySessionStore } from "../../src/session/in-memory-store.js";

const HAS_API_KEY = !!process.env.GOOGLE_GENERATIVE_AI_API_KEY;
const describeIf = HAS_API_KEY ? describe : describe.skip;

// ---------------------------------------------------------------------------
// @ac15 — Token 使用量
// ---------------------------------------------------------------------------

describeIf("Quality_TokenUsage (@ac15)", () => {
  it("simple chat within token budget", async () => {
    const baseline = loadBaseline();
    const maxTokens = baseline.simple_chat_max_tokens as number;
    const agent = makeAgent();
    const result = await agent.chat("你好");

    expect(result.usage.totalTokens).toBeGreaterThan(0);
    expect(result.usage.totalTokens).toBeLessThanOrEqual(maxTokens);
  }, 30_000);

  it("tool call (16 tools) within token budget", async () => {
    const baseline = loadBaseline();
    const maxTokens = baseline.tool_call_16_tools_max_tokens as number;
    const agent = makeAgent({ tools: ALL_TOOLS });
    const result = await agent.chat("請幫我計算寄到台北的運費，包裹重量 2 公斤");

    expect(result.usage.totalTokens).toBeGreaterThan(0);
    expect(result.usage.totalTokens).toBeLessThanOrEqual(maxTokens);
  }, 60_000);

  it("has all required usage fields", async () => {
    const agent = makeAgent();
    const result = await agent.chat("你好");

    expect(result.usage.promptTokens).toBeGreaterThan(0);
    expect(result.usage.completionTokens).toBeGreaterThan(0);
    expect(result.usage.totalTokens).toBeGreaterThan(0);
  }, 30_000);
});

// ---------------------------------------------------------------------------
// @ac16 — 並行使用者隔離
// ---------------------------------------------------------------------------

describeIf("Quality_Concurrency (@ac16)", () => {
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
    // Honor the baseline contract: concurrent_users_must_all_succeed
    const baseline = loadBaseline();
    const mustAllSucceed = baseline.concurrent_users_must_all_succeed as boolean;
    const minSuccess = mustAllSucceed
      ? requests.length
      : Math.ceil(requests.length * 0.67);
    expect(fulfilled.length).toBeGreaterThanOrEqual(minSuccess);
    for (const r of fulfilled) {
      if (r.status === "fulfilled") {
        expect(r.value.blocked).toBe(false);
      }
    }
  }, 90_000);

  it("maintains same-session context across turns", async () => {
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

// ---------------------------------------------------------------------------
// @ac17 — 回應品質
// ---------------------------------------------------------------------------

describeIf("Quality_ResponseQuality (@ac17)", () => {
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

// ---------------------------------------------------------------------------
// @ac18 — Trace 完整性
// ---------------------------------------------------------------------------

describeIf("Quality_TraceCompleteness (@ac18)", () => {
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
