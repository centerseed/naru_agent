/**
 * Tool Calling Integration Tests — @ac3, @ac4, @ac5
 *
 * Covers:
 *   @ac3 — 單工具選擇 + 閒聊不觸發工具
 *   @ac4 — 多工具鏈式呼叫
 *   @ac5 — 並行工具執行
 *
 * Execute:
 *   GOOGLE_GENERATIVE_AI_API_KEY=xxx npx vitest run tests/integration/test_tool_calling.test.ts
 */

import { describe, it, expect, beforeEach } from "vitest";
import {
  callLog,
  clearCallLog,
  ALL_TOOLS,
  makeAgent,
} from "./helpers.js";
import { assertScenarioResult, loadScenarios } from "./scenario-runner.js";

const HAS_API_KEY = !!process.env.GOOGLE_GENERATIVE_AI_API_KEY;
const describeIf = HAS_API_KEY ? describe : describe.skip;

const scenarios = loadScenarios("tool-calling.json");

// ---------------------------------------------------------------------------
// @ac3 — 單一工具選擇
// ---------------------------------------------------------------------------

describeIf("ToolCalling_SingleTool (@ac3)", () => {
  beforeEach(() => clearCallLog());

  it("selects correct tool from 16 — calculate_shipping_cost", async () => {
    const s = scenarios.scenarios.find((s) => s.id === "single_tool_selection")!;
    const agent = makeAgent({ tools: ALL_TOOLS });
    const result = await agent.chat(s.input!);

    assertScenarioResult(result, s.expect);
  }, 60_000);

  it("chitchat does not trigger any tools", async () => {
    const s = scenarios.scenarios.find((s) => s.id === "chitchat_no_tools")!;
    const agent = makeAgent({ tools: ALL_TOOLS });
    const result = await agent.chat(s.input!);

    assertScenarioResult(result, s.expect);
  }, 60_000);

  it("tool result data is reflected in response", async () => {
    const s = scenarios.scenarios.find((s) => s.id === "tool_result_in_response")!;
    const agent = makeAgent({ tools: ALL_TOOLS });
    const result = await agent.chat(s.input!);

    assertScenarioResult(result, s.expect);
  }, 60_000);
});

// ---------------------------------------------------------------------------
// @ac4 — 多工具鏈式呼叫
// ---------------------------------------------------------------------------

describeIf("ToolCalling_MultiToolChaining (@ac4)", () => {
  beforeEach(() => clearCallLog());

  it("chains tools: search → detail/inventory", async () => {
    const s = scenarios.scenarios.find((s) => s.id === "multi_tool_chaining")!;
    const agent = makeAgent({ tools: ALL_TOOLS });
    const result = await agent.chat(s.input!);

    assertScenarioResult(result, s.expect);

    // Verify search comes before detail/inventory
    const names = callLog.map((c) => c.tool as string);
    expect(names).toContain("search_products");
    if (names.includes("get_product_detail")) {
      expect(names.indexOf("search_products")).toBeLessThan(
        names.indexOf("get_product_detail"),
      );
    }
  }, 60_000);

  it("chains tools in correct order: search → inventory → order", async () => {
    const s = scenarios.scenarios.find((s) => s.id === "tool_chain_order")!;
    const agent = makeAgent({ tools: ALL_TOOLS });
    await agent.chat(s.input!);

    const names = callLog.map((c) => c.tool as string);
    expect(names).toContain("search_products");
    expect(names).toContain("check_inventory");
    expect(names).toContain("create_order");

    const idxSearch = names.indexOf("search_products");
    const idxInv = names.indexOf("check_inventory");
    const idxOrder = names.indexOf("create_order");
    expect(idxSearch).toBeLessThan(idxInv);
    expect(idxInv).toBeLessThan(idxOrder);
  }, 60_000);
});

// ---------------------------------------------------------------------------
// @ac5 — 並行工具執行
// ---------------------------------------------------------------------------

describeIf("ToolCalling_ParallelExecution (@ac5)", () => {
  beforeEach(() => clearCallLog());

  it("executes multiple independent tools", async () => {
    const s = scenarios.scenarios.find((s) => s.id === "parallel_tool_execution")!;
    const agent = makeAgent({ tools: ALL_TOOLS });
    const result = await agent.chat(s.input!);

    assertScenarioResult(result, s.expect);
  }, 60_000);

  it("does not call tools without required params", async () => {
    const agent = makeAgent({ tools: ALL_TOOLS });
    await agent.chat("告訴我關於物流的事");

    const calcCalls = callLog.filter(
      (c) => c.tool === "calculate_shipping_cost",
    );
    for (const c of calcCalls) {
      expect(c).toHaveProperty("destination");
      expect(c).toHaveProperty("weight");
    }
  }, 60_000);
});
