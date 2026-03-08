/**
 * Shared helpers and 16 e-commerce tools for baseline tests.
 *
 * Usage:
 *   GOOGLE_GENERATIVE_AI_API_KEY=xxx npx vitest run tests/integration/
 */

import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";
import { google } from "@ai-sdk/google";
import { embedMany } from "ai";
import { tool, NaruAgent, JSONLTraceExporter } from "../../src/index.js";
import type { BaseTool, EmbedFn } from "../../src/index.js";
import type { LanguageModel } from "ai";

// ---------------------------------------------------------------------------
// Model setup
// ---------------------------------------------------------------------------

const __dirname = dirname(fileURLToPath(import.meta.url));

export function getModel(): LanguageModel {
  return google(process.env.CHAT_AGENT_MODEL ?? "gemini-2.5-flash-lite");
}

export function getSummaryModel(): LanguageModel {
  return google(process.env.SUMMARY_MODEL ?? "gemma-3-12b-it");
}

export function getEmbedModel() {
  return google.textEmbeddingModel("gemini-embedding-001");
}

export const embedFn: EmbedFn = async (texts: string[]) => {
  const { embeddings } = await embedMany({
    model: getEmbedModel(),
    values: texts,
  });
  return embeddings;
};

// ---------------------------------------------------------------------------
// Baseline loader
// ---------------------------------------------------------------------------

export function loadBaseline(): Record<string, number | boolean> {
  const raw = readFileSync(
    resolve(__dirname, "baselines/quality_baseline.json"),
    "utf-8",
  );
  return JSON.parse(raw);
}

// ---------------------------------------------------------------------------
// Call log (tool execution tracking)
// ---------------------------------------------------------------------------

export const callLog: Array<Record<string, unknown>> = [];

function log(name: string, params: Record<string, unknown>) {
  callLog.push({ tool: name, ...params });
}

export function clearCallLog() {
  callLog.length = 0;
}

// ---------------------------------------------------------------------------
// 16 e-commerce tools
// ---------------------------------------------------------------------------

export const searchProducts = tool({
  name: "search_products",
  description: "搜尋產品，回傳產品列表",
  parameters: z.object({ query: z.string() }),
  execute: async ({ query }) => {
    log("search_products", { query });
    return JSON.stringify([
      { id: "P001", name: "Sony WH-1000XM5 無線耳機", price: 8990 },
      { id: "P002", name: "AirPods Pro 2 無線耳機", price: 7490 },
    ]);
  },
});

export const getProductDetail = tool({
  name: "get_product_detail",
  description: "取得單一產品的詳細資訊",
  parameters: z.object({ product_id: z.string() }),
  execute: async ({ product_id }) => {
    log("get_product_detail", { product_id });
    return JSON.stringify({
      id: product_id,
      name: "Sony WH-1000XM5 無線耳機",
      price: 8990,
      brand: "Sony",
      category: "耳機",
    });
  },
});

export const checkInventory = tool({
  name: "check_inventory",
  description: "查詢產品庫存數量",
  parameters: z.object({ product_id: z.string() }),
  execute: async ({ product_id }) => {
    log("check_inventory", { product_id });
    return JSON.stringify({ product_id, available: 42 });
  },
});

export const createOrder = tool({
  name: "create_order",
  description: "建立新訂單",
  parameters: z.object({
    product_id: z.string(),
    quantity: z.number(),
  }),
  execute: async ({ product_id, quantity }) => {
    log("create_order", { product_id, quantity });
    return JSON.stringify({ order_id: "ORD-12345", status: "created" });
  },
});

export const getOrderStatus = tool({
  name: "get_order_status",
  description: "查詢訂單狀態",
  parameters: z.object({ order_id: z.string() }),
  execute: async ({ order_id }) => {
    log("get_order_status", { order_id });
    return JSON.stringify({ order_id, status: "processing" });
  },
});

export const cancelOrder = tool({
  name: "cancel_order",
  description: "取消訂單",
  parameters: z.object({ order_id: z.string() }),
  execute: async ({ order_id }) => {
    log("cancel_order", { order_id });
    return JSON.stringify({ order_id, status: "cancelled" });
  },
});

export const getUserProfile = tool({
  name: "get_user_profile",
  description: "取得用戶個人資料",
  parameters: z.object({ user_id: z.string() }),
  execute: async ({ user_id }) => {
    log("get_user_profile", { user_id });
    return JSON.stringify({
      user_id,
      name: "Alice",
      email: "alice@example.com",
    });
  },
});

export const updateUserProfile = tool({
  name: "update_user_profile",
  description: "更新用戶資料的某個欄位",
  parameters: z.object({
    user_id: z.string(),
    field: z.string(),
    value: z.string(),
  }),
  execute: async ({ user_id, field, value }) => {
    log("update_user_profile", { user_id, field, value });
    return JSON.stringify({ user_id, updated: { [field]: value } });
  },
});

export const getShippingOptions = tool({
  name: "get_shipping_options",
  description: "查詢到指定目的地的物流選項",
  parameters: z.object({ destination: z.string() }),
  execute: async ({ destination }) => {
    log("get_shipping_options", { destination });
    return JSON.stringify([
      { method: "standard", days: 5 },
      { method: "express", days: 2 },
    ]);
  },
});

export const calculateShippingCost = tool({
  name: "calculate_shipping_cost",
  description: "計算到指定目的地的運費，需提供目的地和包裹重量(公斤)",
  parameters: z.object({
    destination: z.string(),
    weight: z.number(),
  }),
  execute: async ({ destination, weight }) => {
    log("calculate_shipping_cost", { destination, weight });
    const cost = 60 + weight * 25;
    return JSON.stringify({
      destination,
      weight_kg: weight,
      cost_ntd: cost,
    });
  },
});

export const applyCoupon = tool({
  name: "apply_coupon",
  description: "套用優惠券到訂單",
  parameters: z.object({
    order_id: z.string(),
    coupon_code: z.string(),
  }),
  execute: async ({ order_id, coupon_code }) => {
    log("apply_coupon", { order_id, coupon_code });
    return JSON.stringify({ order_id, discount: "10%" });
  },
});

export const getRecommendations = tool({
  name: "get_recommendations",
  description: "根據用戶偏好推薦商品",
  parameters: z.object({ user_id: z.string() }),
  execute: async ({ user_id }) => {
    log("get_recommendations", { user_id });
    return JSON.stringify([
      { id: "P003", name: "Bose QC45" },
      { id: "P004", name: "JBL Tune 770NC" },
    ]);
  },
});

export const submitReview = tool({
  name: "submit_review",
  description: "提交產品評論",
  parameters: z.object({
    product_id: z.string(),
    rating: z.number(),
    comment: z.string(),
  }),
  execute: async ({ product_id, rating, comment }) => {
    log("submit_review", { product_id, rating, comment });
    return JSON.stringify({ status: "submitted", review_id: "R-001" });
  },
});

export const getReviews = tool({
  name: "get_reviews",
  description: "查詢產品的所有評論",
  parameters: z.object({ product_id: z.string() }),
  execute: async ({ product_id }) => {
    log("get_reviews", { product_id });
    return JSON.stringify([
      { rating: 5, comment: "很棒！" },
      { rating: 4, comment: "不錯" },
    ]);
  },
});

export const trackShipment = tool({
  name: "track_shipment",
  description: "追蹤物流包裹狀態",
  parameters: z.object({ tracking_number: z.string() }),
  execute: async ({ tracking_number }) => {
    log("track_shipment", { tracking_number });
    return JSON.stringify({
      tracking_number,
      status: "in_transit",
      location: "台北轉運站",
    });
  },
});

export const contactSupport = tool({
  name: "contact_support",
  description: "聯繫客服，提交問題描述",
  parameters: z.object({ issue: z.string() }),
  execute: async ({ issue }) => {
    log("contact_support", { issue });
    return JSON.stringify({ ticket_id: "TK-9999", status: "opened" });
  },
});

export const ALL_TOOLS: BaseTool[] = [
  searchProducts,
  getProductDetail,
  checkInventory,
  createOrder,
  getOrderStatus,
  cancelOrder,
  getUserProfile,
  updateUserProfile,
  getShippingOptions,
  calculateShippingCost,
  applyCoupon,
  getRecommendations,
  submitReview,
  getReviews,
  trackShipment,
  contactSupport,
];

// ---------------------------------------------------------------------------
// Agent factory
// ---------------------------------------------------------------------------

export function makeAgent(
  opts: {
    tools?: BaseTool[];
    traceFile?: string;
    sessionStore?: import("../../src/session/base.js").BaseSessionStore;
    knowledgeStore?: import("../../src/knowledge/base.js").BaseKnowledgeStore;
    intentClassifier?: import("../../src/intent/base.js").BaseIntentClassifier;
    contextCompression?: boolean;
    summaryModel?: LanguageModel;
    compressionThresholdRounds?: number;
    compressionKeepLastRounds?: number;
  } = {},
): NaruAgent {
  const extra: Record<string, unknown> = {};

  if (opts.traceFile) {
    extra.traceExporters = [new JSONLTraceExporter(opts.traceFile)];
  }

  return new NaruAgent({
    model: getModel(),
    instructions: ["你是一個電商助手，請用繁體中文回覆。"],
    tools: opts.tools ?? [],
    sessionStore: opts.sessionStore,
    knowledgeStore: opts.knowledgeStore,
    intentClassifier: opts.intentClassifier,
    contextCompression: opts.contextCompression,
    summaryModel: opts.summaryModel,
    compressionThresholdRounds: opts.compressionThresholdRounds,
    compressionKeepLastRounds: opts.compressionKeepLastRounds,
    ...extra,
  });
}

// ---------------------------------------------------------------------------
// Knowledge facts
// ---------------------------------------------------------------------------

export const KNOWLEDGE_FACTS = [
  "Naru Agent supports over 100 LLM models through LiteLLM integration.",
  "The default vector database for development is ChromaDB with cosine similarity.",
  "Context compression triggers when conversation rounds exceed the threshold.",
  "Guardrails can use keyword matching, regex patterns, or custom LLM evaluation.",
  "The memory system uses LLM-driven fact extraction followed by reconciliation.",
  "GraphKnowledgeStore uses NetworkX for knowledge graph with BFS-based search.",
  "Tool selection uses embedding similarity to dynamically filter top-k tools.",
];

export const GRAPH_TEXT = `
Aspirin is a medication that treats headaches. Headaches are a symptom of migraines.
Migraines can be caused by stress. Ibuprofen also treats headaches.
Stress can be reduced by meditation. Meditation is related to mindfulness.
`;
