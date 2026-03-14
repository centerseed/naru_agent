/**
 * Context Compression Integration Tests — @ac20
 *
 * Covers:
 *   @ac20 — 長對話壓縮後保留率
 *
 * Execute:
 *   GOOGLE_GENERATIVE_AI_API_KEY=xxx npx vitest run tests/integration/test_compression.test.ts
 */

import { describe, it, expect } from "vitest";
import {
  loadBaseline,
  makeAgent,
  getSummaryModel,
} from "./helpers.js";
import { loadScenarios } from "./scenario-runner.js";
import { InMemorySessionStore } from "../../src/session/in-memory-store.js";

const HAS_API_KEY = !!process.env.GOOGLE_GENERATIVE_AI_API_KEY;
const describeIf = HAS_API_KEY ? describe : describe.skip;

const _scenarios = loadScenarios("memory-compression.json");

// ---------------------------------------------------------------------------
// Helper: compression agent factory
// ---------------------------------------------------------------------------

function makeCompressionAgent(threshold = 3, keepLast = 3) {
  return makeAgent({
    tools: [],
    sessionStore: new InMemorySessionStore(),
    contextCompression: true,
    summaryModel: getSummaryModel(),
    compressionThresholdRounds: threshold,
    compressionKeepLastRounds: keepLast,
  });
}

// ---------------------------------------------------------------------------
// @ac20 — 長對話壓縮
// ---------------------------------------------------------------------------

describeIf("Compression_ContextRetention (@ac20)", () => {
  it("retains compressed content — March 15 deadline", async () => {
    const agent = makeCompressionAgent(3, 3);
    const sid = "retention-test";

    await agent.chat("The project deadline is March 15. Please remember this date.", { sessionId: sid });
    await agent.chat("We need to use Python 3.12 for the project.", { sessionId: sid });
    await agent.chat("The team lead is Dr. Wang.", { sessionId: sid });
    await agent.chat("We should deploy to AWS.", { sessionId: sid }); // triggers compression
    await agent.chat("Let's use PostgreSQL for the database.", { sessionId: sid });

    // Wait for background compression
    await new Promise((r) => setTimeout(r, 3000));

    const result = await agent.chat("What is the project deadline?", { sessionId: sid });
    expect(
      ["March 15", "3月15", "3/15", "三月十五"].some((kw) =>
        result.content.includes(kw),
      ),
    ).toBe(true);
  }, 120_000);

  it("retains multiple facts with min ratio", async () => {
    const agent = makeCompressionAgent(3, 3);
    const sid = "multi-fact-test";

    const facts: Array<[string, string[]]> = [
      ["The budget is $50,000.", ["50,000", "50000", "$50"]],
      ["The client name is Acme Corp.", ["Acme", "acme"]],
      ["The tech stack is React and Node.js.", ["React", "Node", "react", "node"]],
    ];

    for (const [text] of facts) {
      await agent.chat(text, { sessionId: sid });
    }
    await agent.chat("Thanks for noting all that.", { sessionId: sid });
    await agent.chat("Let me review the project details.", { sessionId: sid });

    // Wait for background compression
    await new Promise((r) => setTimeout(r, 3000));

    const baseline = loadBaseline();
    let correct = 0;
    for (const [text, keywords] of facts) {
      const questionPart = text.includes(" is ")
        ? text.split(" is ")[0]
        : text.slice(0, 20);
      const result = await agent.chat(
        `What did I say about: ${questionPart}?`,
        { sessionId: sid },
      );
      if (keywords.some((kw) => result.content.includes(kw))) {
        correct++;
      }
    }

    const ratio = correct / facts.length;
    expect(ratio).toBeGreaterThanOrEqual(
      baseline.compression_retention_min_ratio as number,
    );
  }, 180_000);
});
