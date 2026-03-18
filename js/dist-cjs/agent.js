"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.NaruAgent = void 0;
const ai_1 = require("ai");
const uuid_1 = require("uuid");
const types_js_1 = require("./types.js");
const types_js_2 = require("./decision/types.js");
const tool_planner_js_1 = require("./decision/tool-planner.js");
const event_bus_js_1 = require("./event-bus.js");
const vercel_adapter_js_1 = require("./tools/vercel-adapter.js");
const registry_js_1 = require("./skills/registry.js");
const collector_js_1 = require("./tracing/collector.js");
const compressor_js_1 = require("./compression/compressor.js");
const in_memory_store_js_1 = require("./compression/in-memory-store.js");
const FALLBACK_RESPONSE = "抱歉，我剛剛出了一點狀況，可以再說一次嗎？";
class NaruAgent {
    model;
    name;
    instructions;
    config;
    eventBus;
    skillRegistry = null;
    traceCollector = null;
    contextCompressor = null;
    traceExporters;
    constructor(config) {
        this.model = config.model;
        this.name = config.name ?? "assistant";
        this.instructions = config.instructions ?? [];
        this.config = config;
        this.eventBus = config.eventBus ?? new event_bus_js_1.EventBus();
        this.traceExporters = config.traceExporters ?? [];
        // Skills
        if (config.skills && config.skills.length > 0) {
            this.skillRegistry = new registry_js_1.SkillRegistry(config.skills, config.skillSelector, config.maxActiveSkills ?? 3);
        }
        // Tracing
        if (this.traceExporters.length > 0) {
            this.traceCollector = new collector_js_1.TraceCollector(this.eventBus);
        }
        // Context compression
        if (config.contextCompression) {
            const summaryStore = config.summaryStore ?? new in_memory_store_js_1.InMemorySummaryStore();
            const summaryModel = config.summaryModel ?? config.model;
            this.contextCompressor = new compressor_js_1.ContextCompressor({
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
    async chat(message, options) {
        const startTime = Date.now();
        const userId = options?.userId;
        const sessionId = options?.sessionId ?? (0, uuid_1.v4)();
        const timings = {};
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
        let history = [];
        if (this.config.sessionStore && sessionId) {
            const stored = await this.config.sessionStore.get(sessionId);
            if (stored) {
                const limit = this.config.numHistoryMessages;
                if (limit) {
                    // Cut on pair boundaries (user+assistant) to avoid orphaned messages
                    const pairCount = Math.floor(limit / 2);
                    history = stored.slice(-(pairCount * 2));
                }
                else {
                    history = stored;
                }
            }
        }
        // === 4. LLM Call ===
        this.eventBus.emit("before_llm_call");
        const llmStart = Date.now();
        const vercelTools = activeTools.length > 0 ? (0, vercel_adapter_js_1.toVercelTools)(activeTools) : undefined;
        const toolChoice = activeTools.length > 0
            ? this.resolveToolChoice({
                message,
                userId,
                sessionId,
                intent,
                activeTools,
            })
            : undefined;
        let content = "";
        const toolCallNames = [];
        let usage = {
            promptTokens: 0,
            completionTokens: 0,
            totalTokens: 0,
        };
        try {
            const result = await (0, ai_1.generateText)({
                model: this.model,
                system: prefetched.systemPrompt,
                messages: [
                    ...history,
                    { role: "user", content: message },
                ],
                tools: vercelTools,
                toolChoice,
                stopWhen: (0, ai_1.stepCountIs)(this.config.toolCallLimit ?? 10),
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
                    if (stepText) {
                        content = stepText;
                        break;
                    }
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
            usage = (0, types_js_1.normalizeUsage)(result.usage);
        }
        catch (err) {
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
        const updatedHistory = [
            ...history,
            { role: "user", content: message },
            { role: "assistant", content: storedAssistant },
        ];
        if (this.config.sessionStore && sessionId) {
            this.config.sessionStore.save(sessionId, updatedHistory).catch(() => { });
        }
        if (this.config.memoryManager && userId) {
            this.config.memoryManager
                .add(userId, [
                { role: "user", content: message },
                { role: "assistant", content },
            ])
                .catch(() => { });
        }
        if (this.contextCompressor && sessionId) {
            this.contextCompressor
                .maybeCompress(sessionId, updatedHistory)
                .catch(() => { });
        }
        // Trace export
        const trace = this.traceCollector?.endTrace(naruResult) ?? null;
        naruResult.trace = trace;
        if (trace) {
            for (const exporter of this.traceExporters) {
                exporter.export(trace).catch(() => { });
            }
        }
        this.eventBus.emit("chat_complete", naruResult);
        return naruResult;
    }
    /**
     * Shared prefetch logic for chat() and chatStream().
     */
    async prefetch(message, sessionId, options, skip) {
        const userId = options?.userId;
        const prefetchTimeout = this.config.prefetchTimeout ?? 10000;
        // === Parallel Prefetch ===
        const prefetchTasks = {};
        if (this.config.memoryManager && userId) {
            prefetchTasks.memory = this.config.memoryManager
                .getContextString(userId, message)
                .catch(() => "");
        }
        if (this.config.intentClassifier && !skip?.intent) {
            prefetchTasks.intent = this.config.intentClassifier
                .classify(message)
                .catch(() => ({ needsKnowledge: true, needsTools: true, raw: "YY" }));
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
        const prefetchResults = await Promise.allSettled(prefetchKeys.map((key) => Promise.race([
            prefetchTasks[key],
            new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), prefetchTimeout)),
        ])));
        const prefetchData = {};
        for (let i = 0; i < prefetchKeys.length; i++) {
            const result = prefetchResults[i];
            prefetchData[prefetchKeys[i]] =
                result.status === "fulfilled" ? result.value : null;
        }
        const memoryContext = prefetchData.memory ?? "";
        const intent = prefetchData.intent ?? null;
        const summaryData = prefetchData.summary;
        if (memoryContext)
            this.eventBus.emit("memory_retrieved", { memoryContext });
        if (intent)
            this.eventBus.emit("intent_classified", intent);
        // === Knowledge Retrieval ===
        let knowledgeContext = "";
        if (this.config.knowledgeStore &&
            (intent?.needsKnowledge ?? true)) {
            try {
                const results = await this.config.knowledgeStore.search(message, this.config.knowledgeTopK ?? 3);
                knowledgeContext = this.config.knowledgeStore.formatContext(results, this.config.knowledgeMinScore ?? 0.3);
                if (knowledgeContext) {
                    this.eventBus.emit("knowledge_retrieved", { knowledgeContext });
                }
            }
            catch {
                // graceful degradation
            }
        }
        // === Skill Execution ===
        let skillResults = [];
        if (this.skillRegistry && !skip?.skills) {
            try {
                const skillContext = {
                    message,
                    userId,
                    sessionId,
                    memoryContext,
                    knowledgeStore: this.config.knowledgeStore,
                };
                skillResults = await this.skillRegistry.runSkills(message, skillContext);
            }
            catch {
                // graceful degradation
            }
        }
        // === Tool Calling Classification ===
        let toolCallingContext = "";
        if (this.config.toolCallingClassifier &&
            !skip?.toolCalling &&
            this.getClassifierTools().length > 0) {
            try {
                const tcResult = await this.config.toolCallingClassifier.classify(message, this.getClassifierTools());
                if (tcResult.toolResults.length > 0) {
                    toolCallingContext = tcResult.toolResults
                        .map((r) => `[${r.tool}]: ${r.result}`)
                        .join("\n");
                    this.eventBus.emit("tool_calling_classified", tcResult);
                }
            }
            catch {
                // graceful degradation
            }
        }
        // === Build Dynamic Instructions ===
        const dynamicInstructions = [...this.instructions];
        if (summaryData?.summaryText) {
            dynamicInstructions.push(`【Conversation History Summary】\n${summaryData.summaryText}`);
        }
        if (knowledgeContext) {
            dynamicInstructions.push(`【Reference Knowledge】\n${knowledgeContext}`);
        }
        if (memoryContext) {
            dynamicInstructions.push(memoryContext);
        }
        for (const key of prefetchKeys) {
            if (key.startsWith("hook_") && prefetchData[key]) {
                dynamicInstructions.push(prefetchData[key]);
            }
        }
        let overridePrompt = null;
        for (const sr of skillResults) {
            if (sr.overrideSystemPrompt) {
                overridePrompt = sr.overrideSystemPrompt;
            }
            if (sr.promptInjection) {
                dynamicInstructions.push(sr.promptInjection);
            }
        }
        if (toolCallingContext) {
            dynamicInstructions.push(`【Tool Results】\n${toolCallingContext}`);
        }
        // === Prepare Tools ===
        const activeTools = [];
        if (intent?.needsTools ?? true) {
            if (this.config.tools)
                activeTools.push(...this.config.tools);
        }
        if (this.config.alwaysTools)
            activeTools.push(...this.config.alwaysTools);
        for (const sr of skillResults) {
            activeTools.push(...sr.extraTools);
        }
        const systemPrompt = overridePrompt ?? dynamicInstructions.join("\n\n");
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
    async *chatStream(message, options) {
        const sessionId = options?.sessionId ?? (0, uuid_1.v4)();
        const userId = options?.userId;
        // === Input Guardrails ===
        if (this.config.guardrails) {
            for (const guardrail of this.config.guardrails) {
                const result = await guardrail.checkInput(message);
                if (!result.passed) {
                    yield { type: "text-delta", text: result.reason ?? "Blocked." };
                    return;
                }
            }
        }
        // === Prefetch ===
        const prefetched = await this.prefetch(message, sessionId, options);
        // Load history
        let history = [];
        if (this.config.sessionStore && sessionId) {
            const stored = await this.config.sessionStore.get(sessionId);
            if (stored) {
                const limit = this.config.numHistoryMessages;
                if (limit) {
                    const pairCount = Math.floor(limit / 2);
                    history = stored.slice(-(pairCount * 2));
                }
                else {
                    history = stored;
                }
            }
        }
        const vercelTools = prefetched.activeTools.length > 0
            ? (0, vercel_adapter_js_1.toVercelTools)(prefetched.activeTools)
            : undefined;
        const toolChoice = prefetched.activeTools.length > 0
            ? this.resolveToolChoice({
                message,
                userId,
                sessionId,
                intent: prefetched.intent,
                activeTools: prefetched.activeTools,
            })
            : undefined;
        const result = (0, ai_1.streamText)({
            model: this.model,
            system: prefetched.systemPrompt,
            messages: [
                ...history,
                { role: "user", content: message },
            ],
            tools: vercelTools,
            toolChoice,
            stopWhen: (0, ai_1.stepCountIs)(this.config.toolCallLimit ?? 10),
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
            yield part;
        }
        // === Background: save session, memory, compression ===
        const updatedHistory = [
            ...history,
            { role: "user", content: message },
            { role: "assistant", content: fullContent },
        ];
        if (this.config.sessionStore && sessionId) {
            this.config.sessionStore.save(sessionId, updatedHistory).catch(() => { });
        }
        if (this.config.memoryManager && userId) {
            this.config.memoryManager
                .add(userId, [
                { role: "user", content: message },
                { role: "assistant", content: fullContent },
            ])
                .catch(() => { });
        }
        if (this.contextCompressor && sessionId) {
            this.contextCompressor
                .maybeCompress(sessionId, updatedHistory)
                .catch(() => { });
        }
    }
    /**
     * Structured decision mode — uses full prefetch context (memory, summary,
     * knowledge, hooks) but returns a typed JSON decision instead of generating
     * a natural-language response or executing tools.
     */
    async decide(message, classifier, options) {
        const startTime = Date.now();
        const userId = options?.userId;
        const sessionId = options?.sessionId ?? (0, uuid_1.v4)();
        const timings = {};
        // Start trace
        const traceId = this.traceCollector?.startTrace(message, userId, sessionId) ?? null;
        // === 1. Input Guardrails ===
        if (this.config.guardrails) {
            for (const guardrail of this.config.guardrails) {
                const result = await guardrail.checkInput(message);
                if (!result.passed) {
                    throw new types_js_2.DecisionError(result.reason ?? "Blocked by input guardrail.");
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
            if (di === prefetched.memoryContext)
                continue;
            if (prefetched.summaryData?.summaryText && di.includes(prefetched.summaryData.summaryText))
                continue;
            if (prefetched.knowledgeContext && di.includes(prefetched.knowledgeContext))
                continue;
            if (!hookInstructions.includes(di))
                hookInstructions.push(di);
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
                if (allTools.length === 0)
                    return undefined;
                const planner = new tool_planner_js_1.ToolPlanner({ model: this.model });
                const plan = await planner.plan(message, allTools);
                timings.toolPlan = Date.now() - planStart;
                return plan;
            })().catch(() => undefined)
            : Promise.resolve(undefined);
        let classifierOutput;
        let toolPlan;
        try {
            [classifierOutput, toolPlan] = await Promise.all([classifyPromise, toolPlanPromise]);
        }
        catch (err) {
            throw new types_js_2.DecisionError("Classifier failed", err, err instanceof Error ? err.message : String(err));
        }
        timings.classify = Date.now() - classifyStart;
        // === 5. Build Result ===
        timings.total = Date.now() - startTime;
        const decisionResult = {
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
                .catch(() => { });
        }
        return decisionResult;
    }
    getEventBus() {
        return this.eventBus;
    }
    makeResult(partial) {
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
    resolveToolChoice(context) {
        return this.config.toolChoiceResolver?.(context) ?? this.config.toolChoice;
    }
    getClassifierTools() {
        const tools = [];
        if (this.config.tools)
            tools.push(...this.config.tools);
        if (this.config.alwaysTools)
            tools.push(...this.config.alwaysTools);
        return dedupeToolsByName(tools);
    }
}
exports.NaruAgent = NaruAgent;
function dedupeToolsByName(tools) {
    const seen = new Set();
    return tools.filter((tool) => {
        if (seen.has(tool.name))
            return false;
        seen.add(tool.name);
        return true;
    });
}
