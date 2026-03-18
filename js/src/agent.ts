import {
  generateText,
  streamText,
  stepCountIs,
  type LanguageModel,
  type ModelMessage,
  type TextStreamPart,
  type ToolSet,
  type ToolChoice,
} from "ai";
import { v4 as uuidv4 } from "uuid";
import type {
  NaruAgentConfig,
  NaruResult,
  ChatOptions,
  TokenUsage,
  IntentResult,
} from "./types.js";
import { normalizeUsage } from "./types.js";
import type {
  StructuredClassifier,
  DecisionAgentResult,
  DecisionOptions,
} from "./decision/types.js";
import { DecisionError } from "./decision/types.js";
import { ToolPlanner } from "./decision/tool-planner.js";
import { EventBus } from "./event-bus.js";
import { toVercelTools } from "./tools/vercel-adapter.js";
import type { BaseTool } from "./tools/base.js";
import type { SkillContext, SkillResult } from "./skills/base.js";
import { SkillRegistry } from "./skills/registry.js";
import { TraceCollector } from "./tracing/collector.js";
import { ContextCompressor } from "./compression/compressor.js";
import { InMemorySummaryStore } from "./compression/in-memory-store.js";
import type { BaseTraceExporter } from "./tracing/exporters/jsonl.js";

const FALLBACK_RESPONSE = "抱歉，我剛剛出了一點狀況，可以再說一次嗎？";

export class NaruAgent {
  private model: LanguageModel;
  private name: string;
  private instructions: string[];
  private config: NaruAgentConfig;
  private eventBus: EventBus;
  private skillRegistry: SkillRegistry | null = null;
  private traceCollector: TraceCollector | null = null;
  private contextCompressor: ContextCompressor | null = null;
  private traceExporters: BaseTraceExporter[];

  constructor(config: NaruAgentConfig) {
    this.model = config.model;
    this.name = config.name ?? "assistant";
    this.instructions = config.instructions ?? [];
    this.config = config;
    this.eventBus = config.eventBus ?? new EventBus();
    this.traceExporters = config.traceExporters ?? [];

    // Skills
    if (config.skills && config.skills.length > 0) {
      this.skillRegistry = new SkillRegistry(
        config.skills,
        config.skillSelector,
        config.maxActiveSkills ?? 3,
      );
    }

    // Tracing
    if (this.traceExporters.length > 0) {
      this.traceCollector = new TraceCollector(this.eventBus);
    }

    // Context compression
    if (config.contextCompression) {
      const summaryStore = config.summaryStore ?? new InMemorySummaryStore();
      const summaryModel = config.summaryModel ?? config.model;
      this.contextCompressor = new ContextCompressor({
        summaryStore,
        summaryModel,
        keepLastRounds: config.compressionKeepLastRounds ?? 5,
        thresholdRounds: config.compressionThresholdRounds ?? 5,
      });
    }
  }

  /**
   * Main chat method — full orchestration loop.
   */
  async chat(
    message: string,
    options?: ChatOptions,
  ): Promise<NaruResult> {
    const startTime = Date.now();
    const userId = options?.userId;
    const sessionId = options?.sessionId ?? uuidv4();
    const timings: Record<string, number> = {};

    // Start trace
    const traceId = this.traceCollector?.startTrace(message, userId, sessionId);

    // === 1. Input Guardrails ===
    if (this.config.guardrails) {
      for (const guardrail of this.config.guardrails) {
        const result = await guardrail.checkInput(message);
        if (!result.passed) {
          const naruResult = this.makeResult({
            content: result.reason ?? "Blocked.",
            blocked: true,
            sessionId,
            traceId: traceId ?? null,
          });
          this.traceCollector?.endTrace(naruResult);
          return naruResult;
        }
      }
    }

    // === 2. Prefetch ===
    const prefetchStart = Date.now();
    const prefetched = await this.prefetch(message, sessionId, options);
    timings.prefetch = Date.now() - prefetchStart;

    const { intent, activeTools } = prefetched;

    // === 3. Load Session History ===
    let history: ModelMessage[] = [];
    if (this.config.sessionStore && sessionId) {
      const stored = await this.config.sessionStore.get(sessionId);
      if (stored) {
        const limit = this.config.numHistoryMessages;
        if (limit) {
          // Cut on pair boundaries (user+assistant) to avoid orphaned messages
          const pairCount = Math.floor(limit / 2);
          history = stored.slice(-(pairCount * 2));
        } else {
          history = stored;
        }
      }
    }

    // === 4. LLM Call ===
    this.eventBus.emit("before_llm_call");
    const llmStart = Date.now();

    const vercelTools =
      activeTools.length > 0 ? toVercelTools(activeTools) : undefined;
    const toolChoice =
      activeTools.length > 0
        ? this.resolveToolChoice({
            message,
            userId,
            sessionId,
            intent,
            activeTools,
          })
        : undefined;

    let content = "";
    const toolCallNames: string[] = [];
    let usage: TokenUsage = {
      promptTokens: 0,
      completionTokens: 0,
      totalTokens: 0,
    };

    try {
      const result = await generateText({
        model: this.model,
        system: prefetched.systemPrompt,
        messages: [
          ...history,
          { role: "user" as const, content: message },
        ],
        tools: vercelTools,
        toolChoice,
        stopWhen: stepCountIs(this.config.toolCallLimit ?? 10),
        temperature: this.config.temperature ?? 0.7,
        providerOptions: this.config.promptCaching ? {
          anthropic: { cacheControl: true },
        } : undefined,
      });

      // Some models (e.g. Gemini) return empty result.text when tool calls are the last step.
      // Fall back to last step with non-empty text.
      content = result.text || "";
      if (!content && result.steps?.length) {
        for (let i = result.steps.length - 1; i >= 0; i--) {
          const stepText = result.steps[i].text;
          if (stepText) { content = stepText; break; }
        }
      }
      if (!content) {
        content = FALLBACK_RESPONSE;
      }

      // Extract tool calls from all steps
      for (const step of result.steps ?? []) {
        for (const tc of step.toolCalls ?? []) {
          toolCallNames.push(tc.toolName);
        }
      }

      usage = normalizeUsage(result.usage);
    } catch (err) {
      console.error("[NaruAgent] generateText failed:", err);
      content = FALLBACK_RESPONSE;
    }

    timings.llm = Date.now() - llmStart;
    this.eventBus.emit("after_llm_call");

    // === 5. Output Guardrails ===
    if (this.config.guardrails && content) {
      for (const guardrail of this.config.guardrails) {
        const result = await guardrail.checkOutput(content);
        if (!result.passed) {
          content = result.modifiedText ?? "I cannot provide that response.";
        }
      }
    }

    // === 6. Build Result ===
    timings.total = Date.now() - startTime;

    const naruResult = this.makeResult({
      content,
      blocked: false,
      usage,
      intent,
      toolCalls: toolCallNames,
      timings,
      sessionId,
      traceId: traceId ?? null,
    });

    // === 7. Background Tasks ===
    // Truncate assistant message before storing if historyAssistantMaxChars is set.
    const maxChars = this.config.historyAssistantMaxChars;
    const storedAssistant = maxChars && content.length > maxChars
      ? content.slice(0, maxChars) + "…"
      : content;
    const updatedHistory: ModelMessage[] = [
      ...history,
      { role: "user" as const, content: message },
      { role: "assistant" as const, content: storedAssistant },
    ];

    if (this.config.sessionStore && sessionId) {
      this.config.sessionStore.save(sessionId, updatedHistory).catch(() => {});
    }

    if (this.config.memoryManager && userId) {
      this.config.memoryManager
        .add(userId, [
          { role: "user", content: message },
          { role: "assistant", content },
        ])
        .catch(() => {});
    }

    if (this.contextCompressor && sessionId) {
      this.contextCompressor
        .maybeCompress(sessionId, updatedHistory)
        .catch(() => {});
    }

    // Trace export
    const trace = this.traceCollector?.endTrace(naruResult) ?? null;
    naruResult.trace = trace;
    if (trace) {
      for (const exporter of this.traceExporters) {
        exporter.export(trace).catch(() => {});
      }
    }

    this.eventBus.emit("chat_complete", naruResult);

    return naruResult;
  }

  /**
   * Shared prefetch logic for chat() and chatStream().
   */
  private async prefetch(
    message: string,
    sessionId: string,
    options?: ChatOptions,
    skip?: { intent?: boolean; skills?: boolean; toolCalling?: boolean },
  ) {
    const userId = options?.userId;
    const prefetchTimeout = this.config.prefetchTimeout ?? 10000;

    // === Parallel Prefetch ===
    const prefetchTasks: Record<string, Promise<unknown>> = {};

    if (this.config.memoryManager && userId) {
      prefetchTasks.memory = this.config.memoryManager
        .getContextString(userId, message)
        .catch(() => "");
    }

    if (this.config.intentClassifier && !skip?.intent) {
      prefetchTasks.intent = this.config.intentClassifier
        .classify(message)
        .catch((): IntentResult => ({ needsKnowledge: true, needsTools: true, raw: "YY" }));
    }

    if (this.contextCompressor && sessionId) {
      prefetchTasks.summary = this.contextCompressor
        .getSummary(sessionId)
        .catch(() => null);
    }

    if (this.config.prefetchHooks) {
      for (let i = 0; i < this.config.prefetchHooks.length; i++) {
        const hook = this.config.prefetchHooks[i];
        prefetchTasks[`hook_${i}`] = hook(message, userId).catch(() => "");
      }
    }

    const prefetchKeys = Object.keys(prefetchTasks);
    const prefetchResults = await Promise.allSettled(
      prefetchKeys.map((key) =>
        Promise.race([
          prefetchTasks[key],
          new Promise((_, reject) =>
            setTimeout(() => reject(new Error("timeout")), prefetchTimeout),
          ),
        ]),
      ),
    );

    const prefetchData: Record<string, unknown> = {};
    for (let i = 0; i < prefetchKeys.length; i++) {
      const result = prefetchResults[i];
      prefetchData[prefetchKeys[i]] =
        result.status === "fulfilled" ? result.value : null;
    }

    const memoryContext = (prefetchData.memory as string) ?? "";
    const intent = (prefetchData.intent as IntentResult) ?? null;
    const summaryData = prefetchData.summary as
      | { summaryText: string }
      | null;

    if (memoryContext) this.eventBus.emit("memory_retrieved", { memoryContext });
    if (intent) this.eventBus.emit("intent_classified", intent);

    // === Knowledge Retrieval ===
    let knowledgeContext = "";
    if (
      this.config.knowledgeStore &&
      (intent?.needsKnowledge ?? true)
    ) {
      try {
        const results = await this.config.knowledgeStore.search(
          message,
          this.config.knowledgeTopK ?? 3,
        );
        knowledgeContext = this.config.knowledgeStore.formatContext(
          results,
          this.config.knowledgeMinScore ?? 0.3,
        );
        if (knowledgeContext) {
          this.eventBus.emit("knowledge_retrieved", { knowledgeContext });
        }
      } catch {
        // graceful degradation
      }
    }

    // === Skill Execution ===
    let skillResults: SkillResult[] = [];
    if (this.skillRegistry && !skip?.skills) {
      try {
        const skillContext: SkillContext = {
          message,
          userId,
          sessionId,
          memoryContext,
          knowledgeStore: this.config.knowledgeStore,
        };
        skillResults = await this.skillRegistry.runSkills(message, skillContext);
      } catch {
        // graceful degradation
      }
    }

    // === Tool Calling Classification ===
    let toolCallingContext = "";
    if (
      this.config.toolCallingClassifier &&
      !skip?.toolCalling &&
      this.getClassifierTools().length > 0
    ) {
      try {
        const tcResult = await this.config.toolCallingClassifier.classify(
          message,
          this.getClassifierTools(),
        );
        if (tcResult.toolResults.length > 0) {
          toolCallingContext = tcResult.toolResults
            .map((r) => `[${r.tool}]: ${r.result}`)
            .join("\n");
          this.eventBus.emit("tool_calling_classified", tcResult);
        }
      } catch {
        // graceful degradation
      }
    }

    // === Build Dynamic Instructions ===
    const dynamicInstructions: string[] = [...this.instructions];

    if (summaryData?.summaryText) {
      dynamicInstructions.push(
        `【Conversation History Summary】\n${summaryData.summaryText}`,
      );
    }
    if (knowledgeContext) {
      dynamicInstructions.push(
        `【Reference Knowledge】\n${knowledgeContext}`,
      );
    }
    if (memoryContext) {
      dynamicInstructions.push(memoryContext);
    }

    for (const key of prefetchKeys) {
      if (key.startsWith("hook_") && prefetchData[key]) {
        dynamicInstructions.push(prefetchData[key] as string);
      }
    }

    let overridePrompt: string | null = null;
    for (const sr of skillResults) {
      if (sr.overrideSystemPrompt) {
        overridePrompt = sr.overrideSystemPrompt;
      }
      if (sr.promptInjection) {
        dynamicInstructions.push(sr.promptInjection);
      }
    }

    if (toolCallingContext) {
      dynamicInstructions.push(
        `【Tool Results】\n${toolCallingContext}`,
      );
    }

    // === Prepare Tools ===
    const activeTools: BaseTool[] = [];
    if (intent?.needsTools ?? true) {
      if (this.config.tools) activeTools.push(...this.config.tools);
    }
    if (this.config.alwaysTools) activeTools.push(...this.config.alwaysTools);
    for (const sr of skillResults) {
      activeTools.push(...sr.extraTools);
    }

    const systemPrompt =
      overridePrompt ?? dynamicInstructions.join("\n\n");

    return {
      memoryContext,
      intent,
      summaryData,
      knowledgeContext,
      skillResults,
      toolCallingContext,
      dynamicInstructions,
      activeTools,
      systemPrompt,
    };
  }

  /**
   * Streaming chat — returns an async iterable of text stream parts.
   */
  async *chatStream(
    message: string,
    options?: ChatOptions,
  ): AsyncIterable<TextStreamPart<ToolSet>> {
    const sessionId = options?.sessionId ?? uuidv4();
    const userId = options?.userId;

    // === Input Guardrails ===
    if (this.config.guardrails) {
      for (const guardrail of this.config.guardrails) {
        const result = await guardrail.checkInput(message);
        if (!result.passed) {
          yield { type: "text-delta", text: result.reason ?? "Blocked." } as TextStreamPart<ToolSet>;
          return;
        }
      }
    }

    // === Prefetch ===
    const prefetched = await this.prefetch(message, sessionId, options);

    // Load history
    let history: ModelMessage[] = [];
    if (this.config.sessionStore && sessionId) {
      const stored = await this.config.sessionStore.get(sessionId);
      if (stored) {
        const limit = this.config.numHistoryMessages;
        if (limit) {
          const pairCount = Math.floor(limit / 2);
          history = stored.slice(-(pairCount * 2));
        } else {
          history = stored;
        }
      }
    }

    const vercelTools =
      prefetched.activeTools.length > 0
        ? toVercelTools(prefetched.activeTools)
        : undefined;
    const toolChoice =
      prefetched.activeTools.length > 0
        ? this.resolveToolChoice({
            message,
            userId,
            sessionId,
            intent: prefetched.intent,
            activeTools: prefetched.activeTools,
          })
        : undefined;

    const result = streamText({
      model: this.model,
      system: prefetched.systemPrompt,
      messages: [
        ...history,
        { role: "user" as const, content: message },
      ],
      tools: vercelTools,
      toolChoice,
      stopWhen: stepCountIs(this.config.toolCallLimit ?? 10),
      temperature: this.config.temperature ?? 0.7,
      providerOptions: this.config.promptCaching ? {
        anthropic: { cacheControl: true },
      } : undefined,
    });

    let fullContent = "";
    for await (const part of result.fullStream) {
      if (part.type === "text-delta") {
        fullContent += part.text;
      }
      yield part as TextStreamPart<ToolSet>;
    }

    // === Background: save session, memory, compression ===
    const updatedHistory: ModelMessage[] = [
      ...history,
      { role: "user" as const, content: message },
      { role: "assistant" as const, content: fullContent },
    ];

    if (this.config.sessionStore && sessionId) {
      this.config.sessionStore.save(sessionId, updatedHistory).catch(() => {});
    }

    if (this.config.memoryManager && userId) {
      this.config.memoryManager
        .add(userId, [
          { role: "user", content: message },
          { role: "assistant", content: fullContent },
        ])
        .catch(() => {});
    }

    if (this.contextCompressor && sessionId) {
      this.contextCompressor
        .maybeCompress(sessionId, updatedHistory)
        .catch(() => {});
    }
  }

  /**
   * Structured decision mode — uses full prefetch context (memory, summary,
   * knowledge, hooks) but returns a typed JSON decision instead of generating
   * a natural-language response or executing tools.
   */
  async decide<T>(
    message: string,
    classifier: StructuredClassifier<T>,
    options?: DecisionOptions,
  ): Promise<DecisionAgentResult<T>> {
    const startTime = Date.now();
    const userId = options?.userId;
    const sessionId = options?.sessionId ?? uuidv4();
    const timings: Record<string, number> = {};

    // Start trace
    const traceId = this.traceCollector?.startTrace(message, userId, sessionId) ?? null;

    // === 1. Input Guardrails ===
    if (this.config.guardrails) {
      for (const guardrail of this.config.guardrails) {
        const result = await guardrail.checkInput(message);
        if (!result.passed) {
          throw new DecisionError(
            result.reason ?? "Blocked by input guardrail.",
          );
        }
      }
    }

    // === 2. Prefetch (skip intent/skills/toolCalling — not needed for decide) ===
    const prefetchStart = Date.now();
    const prefetched = await this.prefetch(message, sessionId, { userId }, {
      intent: true,
      skills: true,
      toolCalling: true,
    });
    timings.prefetch = Date.now() - prefetchStart;

    // === 3. Assemble StructuredClassifierInput ===
    // Only pass hook-injected instructions as extraContext to avoid
    // double-injecting summary/memory/knowledge (already in dedicated fields).
    const hookInstructions = this.instructions.length > 0
      ? [...this.instructions]
      : [];
    for (const di of prefetched.dynamicInstructions) {
      // Skip items already covered by dedicated fields
      if (di === prefetched.memoryContext) continue;
      if (prefetched.summaryData?.summaryText && di.includes(prefetched.summaryData.summaryText)) continue;
      if (prefetched.knowledgeContext && di.includes(prefetched.knowledgeContext)) continue;
      if (!hookInstructions.includes(di)) hookInstructions.push(di);
    }

    const classifierInput = {
      message,
      sessionId,
      userId,
      summary: prefetched.summaryData?.summaryText ?? null,
      memoryContext: prefetched.memoryContext || undefined,
      knowledgeContext: prefetched.knowledgeContext || undefined,
      extraContext: hookInstructions.length > 0 ? hookInstructions : undefined,
    };

    // === 4. Classify + Optional Tool Planning (parallel) ===
    const classifyStart = Date.now();

    const classifyPromise = classifier.classify(classifierInput);

    const toolPlanPromise = options?.includeToolPlan
      ? (async () => {
          const planStart = Date.now();
          const allTools = this.getClassifierTools();
          if (allTools.length === 0) return undefined;
          const planner = new ToolPlanner({ model: this.model });
          const plan = await planner.plan(message, allTools);
          timings.toolPlan = Date.now() - planStart;
          return plan;
        })().catch(() => undefined)
      : Promise.resolve(undefined);

    let classifierOutput;
    let toolPlan;
    try {
      [classifierOutput, toolPlan] = await Promise.all([classifyPromise, toolPlanPromise]);
    } catch (err) {
      throw new DecisionError(
        "Classifier failed",
        err,
        err instanceof Error ? err.message : String(err),
      );
    }
    timings.classify = Date.now() - classifyStart;

    // === 5. Build Result ===
    timings.total = Date.now() - startTime;

    const decisionResult: DecisionAgentResult<T> = {
      decision: classifierOutput.result,
      rawText: classifierOutput.rawText ?? JSON.stringify(classifierOutput.result),
      usage: {
        promptTokens: classifierOutput.usage?.promptTokens ?? 0,
        completionTokens: classifierOutput.usage?.completionTokens ?? 0,
        totalTokens: classifierOutput.usage?.totalTokens ?? 0,
      },
      timings,
      sessionId,
      traceId,
      trace: {
        classifier: classifier.name ?? "unknown",
        usedSummary: !!prefetched.summaryData?.summaryText,
        usedMemory: !!prefetched.memoryContext,
        usedKnowledge: !!prefetched.knowledgeContext,
        toolPlan,
        classifierTrace: classifierOutput.trace,
      },
    };

    // === 7. Background: memory (user message only, no assistant response) ===
    if (this.config.memoryManager && userId) {
      this.config.memoryManager
        .add(userId, [{ role: "user", content: message }])
        .catch(() => {});
    }

    return decisionResult;
  }

  getEventBus(): EventBus {
    return this.eventBus;
  }

  private makeResult(
    partial: Partial<NaruResult> & { content: string },
  ): NaruResult {
    return {
      blocked: false,
      usage: {
        promptTokens: 0,
        completionTokens: 0,
        totalTokens: 0,
      },
      intent: null,
      toolCalls: [],
      timings: {},
      sessionId: null,
      traceId: null,
      trace: null,
      ...partial,
    };
  }

  private resolveToolChoice(context: {
    message: string;
    userId?: string;
    sessionId?: string;
    intent: IntentResult | null;
    activeTools: BaseTool[];
  }): ToolChoice<Record<string, unknown>> | undefined {
    return this.config.toolChoiceResolver?.(context) ?? this.config.toolChoice;
  }

  private getClassifierTools(): BaseTool[] {
    const tools: BaseTool[] = [];
    if (this.config.tools) tools.push(...this.config.tools);
    if (this.config.alwaysTools) tools.push(...this.config.alwaysTools);
    return dedupeToolsByName(tools);
  }
}

function dedupeToolsByName(tools: BaseTool[]): BaseTool[] {
  const seen = new Set<string>();
  return tools.filter((tool) => {
    if (seen.has(tool.name)) return false;
    seen.add(tool.name);
    return true;
  });
}
