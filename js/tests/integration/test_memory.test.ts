/**
 * Memory Integration Tests — @ac19
 *
 * Covers:
 *   @ac19 — 記憶萃取（MemoryManager）
 *
 * Execute:
 *   GOOGLE_GENERATIVE_AI_API_KEY=xxx npx vitest run tests/integration/test_memory.test.ts
 */

import { describe, it, expect } from "vitest";
import {
  loadBaseline,
  makeAgent,
  getModel,
  embedFn,
} from "./helpers.js";
import { loadScenarios } from "./scenario-runner.js";
import { InMemorySessionStore } from "../../src/session/in-memory-store.js";
import { InMemoryMemoryStore } from "../../src/memory/in-memory-store.js";
import { MemoryManager } from "../../src/memory/manager.js";

const HAS_API_KEY = !!process.env.GOOGLE_GENERATIVE_AI_API_KEY;
const describeIf = HAS_API_KEY ? describe : describe.skip;

const _scenarios = loadScenarios("memory-compression.json");

// ---------------------------------------------------------------------------
// @ac19 — 記憶萃取
// ---------------------------------------------------------------------------

describeIf("Memory_FactExtraction (@ac19)", () => {
  it("extracts and stores facts via MemoryManager", async () => {
    const store = new InMemoryMemoryStore();
    const manager = new MemoryManager({
      model: getModel(),
      store,
      embedFn,
    });

    const messages = [
      { role: "user" as const, content: "我叫 Alice，住在台北，我最喜歡 Python 程式語言。" },
      { role: "assistant" as const, content: "很高興認識你 Alice！台北是個很棒的城市。Python 確實是很優秀的語言。" },
    ];
    await manager.add("test_user", messages);

    const baseline = loadBaseline();
    const items = await store.getAll("test_user");
    expect(items.length).toBeGreaterThanOrEqual(
      baseline.memory_min_extracted_facts as number,
    );
    const allContent = items.map((i) => i.content.toLowerCase()).join(" ");
    expect(
      allContent.includes("alice") ||
        allContent.includes("taipei") ||
        allContent.includes("台北"),
    ).toBe(true);
  }, 60_000);

  it("recalls peanut allergy across turns via session", async () => {
    const sessionStore = new InMemorySessionStore();
    const agent = makeAgent({ tools: [], sessionStore });
    const sid = "mem-recall-test";

    const r1 = await agent.chat("我對花生嚴重過敏，請記住這件事。", {
      sessionId: sid,
    });
    expect(r1.blocked).toBe(false);

    await new Promise((r) => setTimeout(r, 200));

    const r2 = await agent.chat("我有什麼過敏？", { sessionId: sid });
    expect(r2.blocked).toBe(false);
    expect(
      r2.content.includes("花生") || r2.content.toLowerCase().includes("peanut"),
    ).toBe(true);
  }, 60_000);
});
