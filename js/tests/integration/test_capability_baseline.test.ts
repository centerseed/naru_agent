/**
 * Naru Agent JS 能力基線測試套件。
 *
 * 覆蓋：知識圖譜、記憶準確度、壓縮後保留率、tool 精準度、多輪連貫性。
 *
 * 執行：
 *   GOOGLE_GENERATIVE_AI_API_KEY=xxx npx vitest run tests/integration/test_capability_baseline.test.ts
 */

import { describe, it, expect, beforeEach } from "vitest";
import {
  loadBaseline,
  callLog,
  clearCallLog,
  ALL_TOOLS,
  GRAPH_TEXT,
  KNOWLEDGE_FACTS,
  makeAgent,
  getModel,
  getSummaryModel,
  embedFn,
} from "./helpers.js";
import { InMemorySessionStore } from "../../src/session/in-memory-store.js";
import { InMemoryKnowledgeStore } from "../../src/knowledge/in-memory-store.js";
import { InMemoryMemoryStore } from "../../src/memory/in-memory-store.js";
import { MemoryManager } from "../../src/memory/manager.js";
import { GraphKnowledgeStore } from "../../src/knowledge/graph-store.js";

const HAS_API_KEY = !!process.env.GOOGLE_GENERATIVE_AI_API_KEY;

const describeIf = HAS_API_KEY ? describe : describe.skip;

// ===========================================================================
// 1. TestKnowledgeRetrieval — RAG 檢索品質
// ===========================================================================

describeIf("KnowledgeRetrieval", () => {
  let store: InMemoryKnowledgeStore;

  beforeEach(async () => {
    store = new InMemoryKnowledgeStore({ embedFn });
    await store.batchIngest(KNOWLEDGE_FACTS);
  }, 60_000);

  it("agent uses retrieved knowledge (ChromaDB question)", async () => {
    const agent = makeAgent({ knowledgeStore: store });
    const result = await agent.chat("Naru 用什麼向量資料庫？");

    expect(result.blocked).toBe(false);
    expect(
      ["ChromaDB", "chromadb", "cosine"].some((kw) =>
        result.content.includes(kw),
      ),
    ).toBe(true);
  }, 60_000);

  it("agent cites specific facts (fact extraction)", async () => {
    const agent = makeAgent({ knowledgeStore: store });
    const result = await agent.chat("記憶系統如何提取資訊？");

    expect(result.blocked).toBe(false);
    const content = result.content.toLowerCase();
    expect(
      ["fact extraction", "reconciliation", "事實", "萃取", "和解"].some(
        (kw) => content.includes(kw),
      ),
    ).toBe(true);
  }, 60_000);

  it("agent refuses unknown info (pricing)", async () => {
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

// ===========================================================================
// 2. TestKnowledgeGraph — 圖譜品質
// ===========================================================================

describeIf("KnowledgeGraph", () => {
  let store: GraphKnowledgeStore;

  beforeEach(async () => {
    store = new GraphKnowledgeStore({ model: getModel() });
    await store.ingestText(GRAPH_TEXT);
  }, 60_000);

  it("extracts minimum entities", async () => {
    const baseline = loadBaseline();
    const minEntities = baseline.graph_min_entities as number;
    const graph = store.getGraph() as { order: number };
    const n = graph.order; // graphology node count
    expect(n).toBeGreaterThanOrEqual(minEntities);
  });

  it("extracts minimum relations", async () => {
    const baseline = loadBaseline();
    const minRelations = baseline.graph_min_relations as number;
    const graph = store.getGraph() as { size: number };
    const n = graph.size; // graphology edge count
    expect(n).toBeGreaterThanOrEqual(minRelations);
  });

  it("search finds related entities via traversal", async () => {
    const results = await store.search("treats headaches", 5);
    const combined = results.map((r) => r.text.toLowerCase()).join(" ");
    expect(
      combined.includes("aspirin") || combined.includes("ibuprofen"),
    ).toBe(true);

    const results2 = await store.search("reduce stress", 5);
    const combined2 = results2.map((r) => r.text.toLowerCase()).join(" ");
    expect(combined2).toContain("meditation");
  });
}, 120_000);

// ===========================================================================
// 3. TestMemoryRecall — 記憶準確度
// ===========================================================================

describeIf("MemoryRecall", () => {
  it("extracts and stores facts via MemoryManager", async () => {
    const store = new InMemoryMemoryStore();
    const manager = new MemoryManager({
      model: getModel(),
      store,
      embedFn,
    });

    const messages = [
      { role: "user", content: "我叫 Alice，住在台北，我最喜歡 Python 程式語言。" },
      { role: "assistant", content: "很高興認識你 Alice！台北是個很棒的城市。Python 確實是很優秀的語言。" },
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

    // Wait for session save
    await new Promise((r) => setTimeout(r, 200));

    const r2 = await agent.chat("我有什麼過敏？", { sessionId: sid });
    expect(r2.blocked).toBe(false);
    expect(
      r2.content.includes("花生") || r2.content.toLowerCase().includes("peanut"),
    ).toBe(true);
  }, 60_000);
});

// ===========================================================================
// 3. TestContextRetention — 壓縮後保留率
// ===========================================================================

describeIf("ContextRetention", () => {
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

  it("retains compressed content (March 15 deadline)", async () => {
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

// ===========================================================================
// 4. TestToolCallingPrecision — Tool 精準度
// ===========================================================================

describeIf("ToolCallingPrecision", () => {
  beforeEach(() => clearCallLog());

  it("does not call tools for chitchat", async () => {
    const baseline = loadBaseline();
    const agent = makeAgent({ tools: ALL_TOOLS });
    const result = await agent.chat("你好嗎？今天天氣真好。");

    expect(result.toolCalls.length).toBeLessThanOrEqual(
      baseline.chitchat_max_tool_calls as number,
    );
  }, 60_000);

  it("avoids wrong tool without required params", async () => {
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

  it("chains tools in correct order: search → inventory → order", async () => {
    const agent = makeAgent({ tools: ALL_TOOLS });
    await agent.chat("幫我搜尋耳機，然後查第一個產品的庫存，最後幫我訂 2 個");

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

// ===========================================================================
// 5. TestMultiTurnCoherence — 多輪連貫性
// ===========================================================================

describeIf("MultiTurnCoherence", () => {
  beforeEach(() => clearCallLog());

  it("resolves pronouns (第一個多少錢)", async () => {
    const sessionStore = new InMemorySessionStore();
    const agent = makeAgent({ tools: ALL_TOOLS, sessionStore });
    const sid = "pronoun-test";

    await agent.chat("幫我搜尋 Sony 耳機", { sessionId: sid });
    await new Promise((r) => setTimeout(r, 200));
    const result = await agent.chat("第一個多少錢？", { sessionId: sid });

    expect(result.blocked).toBe(false);
    expect(result.content).toContain("8990");
  }, 60_000);

  it("maintains topic continuity (改成 3 個)", async () => {
    const sessionStore = new InMemorySessionStore();
    const agent = makeAgent({ tools: ALL_TOOLS, sessionStore });
    const sid = "topic-test";

    await agent.chat("幫我訂購產品 P001，1 個", { sessionId: sid });
    await new Promise((r) => setTimeout(r, 200));
    clearCallLog();
    await agent.chat("改成 3 個", { sessionId: sid });

    const orderCalls = callLog.filter((c) => c.tool === "create_order");
    expect(orderCalls.length).toBeGreaterThanOrEqual(1);
    const last = orderCalls[orderCalls.length - 1];
    expect(last.quantity).toBe(3);
    expect(last.product_id).toBe("P001");
  }, 60_000);

  it("handles corrections (改成寄到高雄)", async () => {
    const sessionStore = new InMemorySessionStore();
    const agent = makeAgent({ tools: ALL_TOOLS, sessionStore });
    const sid = "correction-test";

    await agent.chat("幫我計算寄到台北的運費，包裹 5 公斤", { sessionId: sid });
    await new Promise((r) => setTimeout(r, 200));
    clearCallLog();
    await agent.chat("不對，改成寄到高雄", { sessionId: sid });

    const shippingCalls = callLog.filter(
      (c) => c.tool === "calculate_shipping_cost",
    );
    expect(shippingCalls.length).toBeGreaterThanOrEqual(1);
    const last = shippingCalls[shippingCalls.length - 1];
    expect(last.destination).toContain("高雄");
  }, 60_000);
});
