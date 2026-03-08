// Core
export { NaruAgent } from "./agent.js";
export type {
  NaruResult,
  NaruAgentConfig,
  ChatOptions,
  TokenUsage,
  IntentResult,
  EmbedFn,
  ModelMessage,
} from "./types.js";
export { EventBus } from "./event-bus.js";

// Tools
export { tool } from "./tools/base.js";
export type { BaseTool, ToolConfig } from "./tools/base.js";
export { toVercelTools } from "./tools/vercel-adapter.js";

// Skills
export { skill, makeSkillResult } from "./skills/base.js";
export type {
  BaseSkill,
  SkillConfig,
  SkillContext,
  SkillResult,
} from "./skills/base.js";
export { SkillRegistry } from "./skills/registry.js";
export { KeywordSkillSelector, EmbeddingSkillSelector } from "./skills/selectors.js";
export type { BaseSkillSelector } from "./skills/selectors.js";

// Memory
export type { MemoryItem, MemoryStore } from "./memory/base.js";
export { formatMemoryContext } from "./memory/base.js";
export { MemoryManager, LLMMemoryManager } from "./memory/manager.js";
export { Mem0MemoryManager } from "./memory/mem0-manager.js";
export { InMemoryMemoryStore } from "./memory/in-memory-store.js";
export { PgVectorMemoryStore } from "./memory/pgvector-store.js";

// Knowledge
export type { KnowledgeResult, BaseKnowledgeStore } from "./knowledge/base.js";
export { formatKnowledgeContext } from "./knowledge/base.js";
export { InMemoryKnowledgeStore } from "./knowledge/in-memory-store.js";
export { ChromaKnowledgeStore } from "./knowledge/chroma-store.js";
export { ChunkContextualizer } from "./knowledge/contextualizer.js";
export { PgVectorKnowledgeStore } from "./knowledge/pgvector-store.js";
export { GraphKnowledgeStore } from "./knowledge/graph-store.js";
export { HybridKnowledgeStore } from "./knowledge/hybrid-store.js";

// Guardrails
export type { GuardrailResult, BaseGuardrail } from "./guardrails/base.js";
export { KeywordGuardrail } from "./guardrails/keyword.js";

// Intent
export type {
  BaseIntentClassifier,
  BaseToolCallingClassifier,
  ToolCallingResult,
} from "./intent/base.js";
export { LLMIntentClassifier } from "./intent/llm-classifier.js";
export { LLMToolCallingClassifier } from "./intent/tool-calling-classifier.js";

// Session
export type { BaseSessionStore } from "./session/base.js";
export { InMemorySessionStore } from "./session/in-memory-store.js";
export { RedisSessionStore } from "./session/redis-store.js";

// Compression
export type { CompressedSummary, BaseSummaryStore } from "./compression/base.js";
export { ContextCompressor } from "./compression/compressor.js";
export { InMemorySummaryStore } from "./compression/in-memory-store.js";

// Tracing
export type { Trace, Span } from "./tracing/trace.js";
export { createTrace, createSpan } from "./tracing/trace.js";
export { TraceCollector } from "./tracing/collector.js";
export type { BaseTraceExporter } from "./tracing/exporters/jsonl.js";
export { JSONLTraceExporter } from "./tracing/exporters/jsonl.js";
