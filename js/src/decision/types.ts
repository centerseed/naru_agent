import type { TokenUsage } from "../types.js";

// ── StructuredClassifier<T> ─────────────────────────────────────────

export interface StructuredClassifierInput {
  message: string;
  sessionId?: string;
  userId?: string;
  summary?: string | null;
  memoryContext?: string;
  knowledgeContext?: string;
  extraContext?: string[];
}

export interface StructuredClassifierOutput<T> {
  result: T;
  rawText?: string;
  usage?: Partial<TokenUsage>;
  trace?: Record<string, unknown>;
}

export interface StructuredClassifier<T> {
  name?: string;
  classify(
    input: StructuredClassifierInput,
  ): Promise<StructuredClassifierOutput<T>>;
}

// ── Tool Planning ───────────────────────────────────────────────────

export interface ToolPlan {
  tool: string;
  args: Record<string, unknown>;
  confidence?: number;
  reasonCodes?: string[];
}

// ── DecisionAgentResult<T> ──────────────────────────────────────────

export interface DecisionAgentResult<T> {
  decision: T;
  rawText: string;
  usage: TokenUsage;
  timings: Record<string, number>;
  sessionId: string;
  traceId: string | null;
  trace?: {
    classifier: string;
    usedSummary: boolean;
    usedMemory: boolean;
    usedKnowledge: boolean;
    toolPlan?: ToolPlan[];
    classifierTrace?: Record<string, unknown>;
  };
}

// ── DecisionOptions ─────────────────────────────────────────────────

export interface DecisionOptions {
  userId?: string;
  sessionId?: string;
  includeToolPlan?: boolean;
}

// ── DecisionError ───────────────────────────────────────────────────

export class DecisionError extends Error {
  constructor(
    message: string,
    public readonly cause?: unknown,
    public readonly rawText?: string,
  ) {
    super(message);
    this.name = "DecisionError";
  }
}
