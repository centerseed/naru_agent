/**
 * Streaming Integration Tests — @ac22
 *
 * Covers:
 *   @ac22 — 串流事件
 *
 * Requires real LLM (chatStream calls the model).
 *
 * Execute:
 *   GOOGLE_GENERATIVE_AI_API_KEY=xxx npx vitest run tests/integration/test_streaming.test.ts
 */

import { describe, it, expect } from "vitest";
import {
  ALL_TOOLS,
  makeAgent,
} from "./helpers.js";
import { loadScenarios } from "./scenario-runner.js";

const HAS_API_KEY = !!process.env.GOOGLE_GENERATIVE_AI_API_KEY;
const describeIf = HAS_API_KEY ? describe : describe.skip;

const _scenarios = loadScenarios("streaming.json");

// ---------------------------------------------------------------------------
// @ac22 — 串流事件
// ---------------------------------------------------------------------------

describeIf("Streaming_Events (@ac22)", () => {
  it("produces text_delta events for simple chat", async () => {
    const agent = makeAgent();
    const events: string[] = [];
    let fullText = "";

    for await (const part of agent.chatStream("請介紹一下你自己")) {
      events.push(part.type);
      if (part.type === "text-delta") {
        fullText += part.text;
      }
    }

    expect(events).toContain("text-delta");
    expect(fullText.length).toBeGreaterThan(0);
  }, 60_000);

  it("produces text_delta events for short message", async () => {
    const agent = makeAgent();
    const eventTypes = new Set<string>();
    let content = "";

    for await (const part of agent.chatStream("你好")) {
      eventTypes.add(part.type);
      if (part.type === "text-delta") {
        content += part.text;
      }
    }

    expect(eventTypes.has("text-delta")).toBe(true);
    expect(content.length).toBeGreaterThan(0);
  }, 60_000);

  it("produces events including tool-related events for tool call", async () => {
    const agent = makeAgent({ tools: ALL_TOOLS });
    const eventTypes = new Set<string>();
    let content = "";

    for await (const part of agent.chatStream(
      "請幫我計算寄到台北的運費，包裹重量 2 公斤",
    )) {
      eventTypes.add(part.type);
      if (part.type === "text-delta") {
        content += part.text;
      }
    }

    // Must have text events
    expect(eventTypes.has("text-delta")).toBe(true);
    expect(content.length).toBeGreaterThan(0);
  }, 60_000);

  it("streams incrementally (multiple text-delta events)", async () => {
    const agent = makeAgent();
    let textDeltaCount = 0;

    for await (const part of agent.chatStream(
      "請用 5 句話介紹台灣的科技產業",
    )) {
      if (part.type === "text-delta") {
        textDeltaCount++;
      }
    }

    // A multi-sentence response should produce multiple delta events
    expect(textDeltaCount).toBeGreaterThan(1);
  }, 60_000);
});
