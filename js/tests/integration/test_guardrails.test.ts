/**
 * Guardrails Integration Tests — @ac21
 *
 * Covers:
 *   @ac21 — 輸入防護（keyword guardrail 不需要真實 LLM）
 *
 * Note: KeywordGuardrail is local and does NOT require an API key.
 *
 * Execute:
 *   npx vitest run tests/integration/test_guardrails.test.ts
 */

import { describe, it, expect } from "vitest";
import {
  makeAgent,
} from "./helpers.js";
import { loadScenarios } from "./scenario-runner.js";
import { KeywordGuardrail } from "../../src/guardrails/keyword.js";

// Guardrail tests do NOT need real LLM — keyword matching is local
const scenarios = loadScenarios("guardrails.json");

interface GuardrailsFile {
  blocked_patterns: string[];
  scenarios: typeof scenarios.scenarios;
}

const guardrailData = scenarios as unknown as GuardrailsFile;
const BLOCKED_PATTERNS = guardrailData.blocked_patterns ?? ["bomb", "hack", "weapon", "炸彈", "攻擊"];

// ---------------------------------------------------------------------------
// @ac21 — 輸入防護
// ---------------------------------------------------------------------------

describe("Guardrails_InputProtection (@ac21)", () => {
  function makeGuardrailAgent() {
    const guardrail = new KeywordGuardrail({
      blockedPatterns: BLOCKED_PATTERNS,
      inputMessage: "This request cannot be processed.",
    });
    return makeAgent({ tools: [], guardrails: [guardrail] });
  }

  it("blocks English keyword — bomb", async () => {
    const s = guardrailData.scenarios.find((s) => s.id === "blocked_input_keyword")!;
    const agent = makeGuardrailAgent();
    const result = await agent.chat(s.input!);

    expect(result.blocked).toBe(true);
  }, 10_000);

  it("blocks Chinese keyword — 炸彈", async () => {
    const s = guardrailData.scenarios.find((s) => s.id === "blocked_input_chinese")!;
    const agent = makeGuardrailAgent();
    const result = await agent.chat(s.input!);

    expect(result.blocked).toBe(true);
  }, 10_000);

  it("allows safe input — order query", async () => {
    const s = guardrailData.scenarios.find((s) => s.id === "allowed_safe_input")!;
    const agent = makeGuardrailAgent();
    const result = await agent.chat(s.input!);

    // Guardrail should not block; LLM may not be available but blocked must be false
    expect(result.blocked).toBe(false);
  }, 60_000);

  it("allows shopping query — no blocked keywords", async () => {
    const s = guardrailData.scenarios.find((s) => s.id === "allowed_shopping_query")!;
    const agent = makeGuardrailAgent();
    const result = await agent.chat(s.input!);

    expect(result.blocked).toBe(false);
  }, 60_000);
});
