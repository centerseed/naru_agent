import {
  generateText,
  streamText,
  stepCountIs,
  type LanguageModel,
  type ModelMessage,
  type TextStreamPart,
  type ToolSet,
} from "ai";
import { v4 as uuidv4 } from "uuid";
import type {
  NaruAgentConfig,
  NaruResult,
  ChatOptions,
  TokenUsage,
  IntentResult,
} from "./types.js";
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

    // === 2. Parallel Prefetch ===
    const prefetchStart = Date.now();
    const prefetchTimeout = this.config.prefetchTimeout ?? 10000;

    const prefetchTasks: Record<string, Promise<unknown>> = {};

    // Memory
    if (this.config.memoryManager && userId) {
      prefetchTasks.memory = this.config.memoryManager
        .getContextString(userId, message)
        .catch(() => "");
    }

    // Intent classification
    if (this.config.intentClassifier) {
      prefetchTasks.intent = this.config.intentClassifier
        .classify(message)
        .catch((): IntentResult => ({ needsKnowledge: true, needsTools: true, raw: "YY" }));
    }

    // Context compression summary
    if (this.contextCompressor && sessionId) {
      prefetchTasks.summary = this.contextCompressor
        .getSummary(sessionId)
        .catch(() => null);
    }

    // Custom prefetch hooks
    if (this.config.prefetchHooks) {
      for (let i = 0; i < this.config.prefetchHooks.length; i++) {
        const hook = this.config.prefetchHooks[i];
        prefetchTasks[`hook_${i}`] = hook(message, userId).catch(() => "");
      }
    }

    // Wait for all with timeout
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

    timings.prefetch = Date.now() - prefetchStart;

    const memoryContext = (prefetchData.memory as string) ?? "";
    const intent = (prefetchData.intent as IntentResult) ?? null;
    const summaryData = prefetchData.summary as
      | { summaryText: string }
      | null;

    // Emit events
    if (memoryContext) this.eventBus.emit("memory_retrieved", { memoryContext });
    if (intent) this.eventBus.emit("intent_classified", intent);

    // === 3. Conditional Knowledge Retrieval ===
    let knowledgeContext = "";
    if (
      this.config.knowledgeStore &&
      (intent?.needsKnowledge ?? true)
    ) {
      try {
        const knowledgeStart = Date.now();
        const results = await this.config.knowledgeStore.search(
          message,
          this.config.knowledgeTopK ?? 3,
        );
        knowledgeContext = this.config.knowledgeStore.formatContext(
          results,
          this.config.knowledgeMinScore ?? 0.3,
        );
        timings.knowledge = Date.now() - knowledgeStart;
        if (knowledgeContext) {
          this.eventBus.emit("knowledge_retrieved", { knowledgeContext });
        }
      } catch {
        // graceful degradation
      }
    }

    // === 4. Skill Execution ===
    let skillResults: SkillResult[] = [];
    if (this.skillRegistry) {
      try {
        const skillStart = Date.now();
        const skillContext: SkillContext = {
          message,
          userId,
          sessionId,
          memoryContext,
          knowledgeStore: this.config.knowledgeStore,
        };
        skillResults = await this.skillRegistry.runSkills(message, skillContext);
        timings.skills = Date.now() - skillStart;
      } catch {
        // graceful degradation
      }
    }

    // === 5. Tool Calling Classification ===
    let toolCallingContext = "";
    if (
      this.config.toolCallingClassifier &&
      this.config.tools?.length
    ) {
      try {
        const tcStart = Date.now();
        const tcResult = await this.config.toolCallingClassifier.classify(
          message,
          this.config.tools,
        );
        if (tcResult.toolResults.length > 0) {
          toolCallingContext = tcResult.toolResults
            .map((r) => `[${r.tool}]: ${r.result}`)
            .join("\n");
          this.eventBus.emit("tool_calling_classified", tcResult);
        }
        timings.toolCalling = Date.now() - tcStart;
      } catch {
        // graceful degradation
      }
    }

    // === 6. Build Dynamic Instructions ===
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

    // Hook results
    for (const key of prefetchKeys) {
      if (key.startsWith("hook_") && prefetchData[key]) {
        dynamicInstructions.push(prefetchData[key] as string);
      }
    }

    // Skill results
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

    // === 7. Prepare Tools ===
    const activeTools: BaseTool[] = [];
    if (intent?.needsTools ?? true) {
      if (this.config.tools) activeTools.push(...this.config.tools);
    }
    if (this.config.alwaysTools) activeTools.push(...this.config.alwaysTools);
    for (const sr of skillResults) {
      activeTools.push(...sr.extraTools);
    }

    // === 8. Load Session History ===
    let history: ModelMessage[] = [];
    if (this.config.sessionStore && sessionId) {
      const stored = await this.config.sessionStore.get(sessionId);
      if (stored) {
        const limit = this.config.numHistoryMessages;
        history = limit ? stored.slice(-limit) : stored;
      }
    }

    // === 9. LLM Call ===
    this.eventBus.emit("before_llm_call");
    const llmStart = Date.now();

    const systemPrompt =
      overridePrompt ?? dynamicInstructions.join("\n\n");
    const vercelTools =
      activeTools.length > 0 ? toVercelTools(activeTools) : undefined;

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
        system: systemPrompt,
        messages: [
          ...history,
          { role: "user" as const, content: message },
        ],
        tools: vercelTools,
        stopWhen: stepCountIs(this.config.toolCallLimit ?? 10),
        temperature: this.config.temperature ?? 0.7,
      });

      content = result.text || "";

      // Extract tool calls from all steps
      for (const step of result.steps ?? []) {
        for (const tc of step.toolCalls ?? []) {
          toolCallNames.push(tc.toolName);
        }
      }

      usage = {
        promptTokens: result.usage?.inputTokens ?? 0,
        completionTokens: result.usage?.outputTokens ?? 0,
        totalTokens: result.usage?.totalTokens ??
          ((result.usage?.inputTokens ?? 0) +
          (result.usage?.outputTokens ?? 0)),
      };
    } catch (err) {
      content = FALLBACK_RESPONSE;
    }

    timings.llm = Date.now() - llmStart;
    this.eventBus.emit("after_llm_call");

    // === 10. Output Guardrails ===
    if (this.config.guardrails && content) {
      for (const guardrail of this.config.guardrails) {
        const result = await guardrail.checkOutput(content);
        if (!result.passed) {
          content = result.modifiedText ?? "I cannot provide that response.";
        }
      }
    }

    // === 11. Build Result ===
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

    // === 12. Background Tasks ===
    const updatedHistory: ModelMessage[] = [
      ...history,
      { role: "user" as const, content: message },
      { role: "assistant" as const, content },
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
   * Streaming chat — returns an async iterable of text stream parts.
   */
  async *chatStream(
    message: string,
    options?: ChatOptions,
  ): AsyncIterable<TextStreamPart<ToolSet>> {
    const sessionId = options?.sessionId ?? uuidv4();
    const userId = options?.userId;

    // Simplified streaming: skip prefetch for now, just stream LLM
    const systemPrompt = this.instructions.join("\n\n");

    // Load history
    let history: ModelMessage[] = [];
    if (this.config.sessionStore && sessionId) {
      const stored = await this.config.sessionStore.get(sessionId);
      if (stored) history = stored;
    }

    const activeTools: BaseTool[] = [
      ...(this.config.tools ?? []),
      ...(this.config.alwaysTools ?? []),
    ];
    const vercelTools =
      activeTools.length > 0 ? toVercelTools(activeTools) : undefined;

    const result = streamText({
      model: this.model,
      system: systemPrompt,
      messages: [
        ...history,
        { role: "user" as const, content: message },
      ],
      tools: vercelTools,
      stopWhen: stepCountIs(this.config.toolCallLimit ?? 10),
      temperature: this.config.temperature ?? 0.7,
    });

    let fullContent = "";
    for await (const part of result.fullStream) {
      if (part.type === "text-delta") {
        fullContent += part.text;
      }
      yield part as TextStreamPart<ToolSet>;
    }

    // Background: save session
    if (this.config.sessionStore && sessionId) {
      const updatedHistory: ModelMessage[] = [
        ...history,
        { role: "user" as const, content: message },
        { role: "assistant" as const, content: fullContent },
      ];
      this.config.sessionStore.save(sessionId, updatedHistory).catch(() => {});
    }
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
}
