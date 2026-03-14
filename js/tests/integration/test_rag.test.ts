/**
 * RAG Integration Tests — @ac6, @ac7
 *
 * Covers:
 *   @ac6 — 向量知識檢索
 *   @ac7 — 知識圖譜查詢
 *
 * Execute:
 *   GOOGLE_GENERATIVE_AI_API_KEY=xxx npx vitest run tests/integration/test_rag.test.ts
 */

import { describe, it, expect, beforeEach } from "vitest";
import {
  loadBaseline,
  KNOWLEDGE_FACTS,
  GRAPH_TEXT,
  makeAgent,
  getModel,
  embedFn,
} from "./helpers.js";
import { loadScenarios } from "./scenario-runner.js";
import { InMemoryKnowledgeStore } from "../../src/knowledge/in-memory-store.js";
import { GraphKnowledgeStore } from "../../src/knowledge/graph-store.js";

const HAS_API_KEY = !!process.env.GOOGLE_GENERATIVE_AI_API_KEY;
const describeIf = HAS_API_KEY ? describe : describe.skip;

const _scenarios = loadScenarios("rag.json");

// ---------------------------------------------------------------------------
// @ac6 — 向量知識檢索
// ---------------------------------------------------------------------------

describeIf("RAG_VectorRetrieval (@ac6)", () => {
  let store: InMemoryKnowledgeStore;

  beforeEach(async () => {
    store = new InMemoryKnowledgeStore({ embedFn });
    await store.batchIngest(KNOWLEDGE_FACTS);
  }, 60_000);

  it("agent uses retrieved knowledge — ChromaDB question", async () => {
    const agent = makeAgent({ knowledgeStore: store });
    const result = await agent.chat("Naru 用什麼向量資料庫？");

    expect(result.blocked).toBe(false);
    expect(
      ["ChromaDB", "chromadb", "cosine"].some((kw) =>
        result.content.includes(kw),
      ),
    ).toBe(true);
  }, 60_000);

  it("agent cites specific facts — fact extraction question", async () => {
    const agent = makeAgent({ knowledgeStore: store });
    const result = await agent.chat("記憶系統如何提取資訊？");

    expect(result.blocked).toBe(false);
    const content = result.content.toLowerCase();
    expect(
      ["fact extraction", "reconciliation", "事實", "萃取", "和解"].some((kw) =>
        content.includes(kw),
      ),
    ).toBe(true);
  }, 60_000);

  it("agent refuses unknown info — pricing question", async () => {
    const agent = makeAgent({ knowledgeStore: store });
    const result = await agent.chat("Naru Agent 的定價是多少？");

    expect(result.blocked).toBe(false);
    const content = result.content.toLowerCase();
    const hasPrice = ["$", "costs", "priced", "usd", "ntd"].some((kw) =>
      content.includes(kw),
    );
    const hasRefusal = [
      "don't have",
      "not sure",
      "沒有",
      "不確定",
      "無法",
      "不清楚",
      "未提供",
    ].some((kw) => content.includes(kw));
    expect(!hasPrice || hasRefusal).toBe(true);
  }, 60_000);
});

// ---------------------------------------------------------------------------
// @ac7 — 知識圖譜查詢
// ---------------------------------------------------------------------------

describeIf("RAG_KnowledgeGraph (@ac7)", () => {
  let store: GraphKnowledgeStore;

  beforeEach(async () => {
    store = new GraphKnowledgeStore({ model: getModel() });
    await store.ingestText(GRAPH_TEXT);
  }, 60_000);

  it("extracts minimum entities from graph text", async () => {
    const baseline = loadBaseline();
    const minEntities = baseline.graph_min_entities as number;
    const graph = store.getGraph() as { order: number };
    expect(graph.order).toBeGreaterThanOrEqual(minEntities);
  });

  it("extracts minimum relations from graph text", async () => {
    const baseline = loadBaseline();
    const minRelations = baseline.graph_min_relations as number;
    const graph = store.getGraph() as { size: number };
    expect(graph.size).toBeGreaterThanOrEqual(minRelations);
  });

  it("search finds medications related to headaches via traversal", async () => {
    const results = await store.search("treats headaches", 5);
    const combined = results.map((r) => r.text.toLowerCase()).join(" ");
    expect(
      combined.includes("aspirin") || combined.includes("ibuprofen"),
    ).toBe(true);
  });

  it("search finds stress reduction methods via traversal", async () => {
    const results = await store.search("reduce stress", 5);
    const combined = results.map((r) => r.text.toLowerCase()).join(" ");
    expect(combined).toContain("meditation");
  });
}, 120_000);
