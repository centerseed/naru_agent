import type { LanguageModel, ModelMessage, ToolChoice } from "ai";
import type { BaseTool } from "./tools/base.js";

export interface TokenUsage {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  cacheReadTokens?: number;
  cacheWriteTokens?: number;
}

/** Map Vercel AI SDK usage shape → naru TokenUsage. */
export function normalizeUsage(
  usage?: { inputTokens?: number; outputTokens?: number; totalTokens?: number },
): TokenUsage {
  const p = usage?.inputTokens ?? 0;
  const c = usage?.outputTokens ?? 0;
  return { promptTokens: p, completionTokens: c, totalTokens: usage?.totalTokens ?? p + c };
}

export interface HandoffRequest {
  target: string;
  message?: string;
  reason?: string;
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
  handoff?: HandoffRequest | null;
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
  toolChoice?: ToolChoice<Record<string, unknown>>;
  toolChoiceResolver?: (context: {
    message: string;
    userId?: string;
    sessionId?: string;
    intent: IntentResult | null;
    activeTools: BaseTool[];
  }) => ToolChoice<Record<string, unknown>> | undefined;

  // Session
  sessionStore?: import("./session/base.js").BaseSessionStore;
  numHistoryMessages?: number;
  /** Max characters to store per assistant message in history. Omit to store full content. */
  historyAssistantMaxChars?: number;

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

  // Provider options
  promptCaching?: boolean;
}

export interface ChatOptions {
  userId?: string;
  sessionId?: string;
}

export type EmbedFn = (texts: string[]) => Promise<number[][]>;

export { ModelMessage };
