import type { LanguageModel, ModelMessage } from "ai";

export interface TokenUsage {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  cacheReadTokens?: number;
  cacheWriteTokens?: number;
}

export interface NaruResult {
  content: string;
  blocked: boolean;
  usage: TokenUsage;
  intent: IntentResult | null;
  toolCalls: string[];
  timings: Record<string, number>;
  sessionId: string | null;
  traceId: string | null;
  trace: import("./tracing/trace.js").Trace | null;
}

export interface IntentResult {
  needsKnowledge: boolean;
  needsTools: boolean;
  raw: string;
}

export interface NaruAgentConfig {
  model: LanguageModel;
  name?: string;
  instructions?: string[];

  // Tools & RAG
  tools?: import("./tools/base.js").BaseTool[];
  alwaysTools?: import("./tools/base.js").BaseTool[];
  knowledgeStore?: import("./knowledge/base.js").BaseKnowledgeStore;
  knowledgeTopK?: number;
  knowledgeMinScore?: number;

  // Intent
  intentClassifier?: import("./intent/base.js").BaseIntentClassifier;
  toolCallingClassifier?: import("./intent/base.js").BaseToolCallingClassifier;

  // Memory
  memoryManager?: import("./memory/manager.js").MemoryManager;

  // Guardrails
  guardrails?: import("./guardrails/base.js").BaseGuardrail[];

  // LLM options
  toolCallLimit?: number;
  temperature?: number;
  prefetchTimeout?: number;

  // Session
  sessionStore?: import("./session/base.js").BaseSessionStore;
  numHistoryMessages?: number;

  // Compression
  contextCompression?: boolean;
  summaryStore?: import("./compression/base.js").BaseSummaryStore;
  summaryModel?: LanguageModel;
  compressionKeepLastRounds?: number;
  compressionThresholdRounds?: number;

  // Extensions
  eventBus?: import("./event-bus.js").EventBus;
  prefetchHooks?: Array<(message: string, userId?: string) => Promise<string>>;
  traceExporters?: import("./tracing/exporters/jsonl.js").BaseTraceExporter[];

  // Skills
  skills?: import("./skills/base.js").BaseSkill[];
  skillSelector?: import("./skills/selectors.js").BaseSkillSelector;
  maxActiveSkills?: number;
}

export interface ChatOptions {
  userId?: string;
  sessionId?: string;
}

export type EmbedFn = (texts: string[]) => Promise<number[][]>;

export { ModelMessage };
