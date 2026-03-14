"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.AgentOrchestrator = void 0;
const uuid_1 = require("uuid");
const pending_js_1 = require("./pending.js");
/**
 * AgentOrchestrator — wraps one or more AgentChatDelegate instances with:
 *   Phase 0: Pending confirmation handling
 *   Phase 1: Intent resolution
 *   Phase 2: Direct execution (bypass LLM)
 *   Phase 3: Delegate routing
 *
 * AgentOrchestrator itself satisfies AgentChatDelegate, enabling nesting.
 */
class AgentOrchestrator {
    config;
    constructor(config) {
        this.config = config;
    }
    async fireHook(fn) {
        if (fn) {
            try {
                await fn();
            }
            catch {
                // hooks do not affect main flow
            }
        }
    }
    async chat(message, options) {
        const startTime = Date.now();
        const traceId = (0, uuid_1.v4)();
        const sessionId = options?.sessionId ?? null;
        const timings = { total: 0 };
        let phaseReached = "delegate";
        let orchestrationIntent = null;
        let directExecutorUsed = null;
        let delegateUsed = null;
        // Fire beforeMessage hook
        await this.fireHook(this.config.lifecycleHooks?.beforeMessage
            ? () => this.config.lifecycleHooks.beforeMessage(message, options)
            : undefined);
        const buildDecisionTrace = (overrides) => ({
            traceId,
            phaseReached: overrides.phaseReached,
            intentResolved: overrides.orchestrationIntent,
            timings: overrides.timings,
            directExecutorUsed: overrides.directExecutorUsed,
            delegateUsed: overrides.delegateUsed,
        });
        const buildFinalResult = (baseResult, overrides) => {
            const decisionTrace = buildDecisionTrace(overrides);
            return {
                ...baseResult,
                content: overrides.content ?? baseResult.content,
                orchestrationIntent: overrides.orchestrationIntent,
                decisionTrace,
                pendingConfirmation: overrides.pendingConfirmation ?? null,
                sessionId: overrides.sessionId !== undefined ? overrides.sessionId : (sessionId ?? baseResult.sessionId),
            };
        };
        // Cache session state to avoid triple fetch within the same chat() call
        let cachedSessionState;
        try {
            // === Phase 0: Pending Confirmation ===
            if (this.config.pendingStateManager && sessionId) {
                const pending = await this.config.pendingStateManager.getPending(sessionId);
                if (pending) {
                    const classifier = this.config.confirmationClassifier ?? pending_js_1.classifyConfirmationDisposition;
                    const disposition = classifier(message);
                    if (disposition === "confirm" || disposition === "reject") {
                        // Handle confirmation/rejection
                        await this.config.pendingStateManager.clearPending(sessionId);
                        phaseReached = "pending_confirmation";
                        timings.total = Date.now() - startTime;
                        const confirmContent = disposition === "confirm"
                            ? `Confirmed: ${pending.type}`
                            : `Rejected: ${pending.type}`;
                        const baseResult = {
                            content: confirmContent,
                            blocked: false,
                            usage: { promptTokens: 0, completionTokens: 0, totalTokens: 0 },
                            intent: null,
                            toolCalls: [],
                            timings: { total: timings.total },
                            sessionId,
                            traceId,
                            trace: null,
                        };
                        const result = buildFinalResult(baseResult, {
                            phaseReached,
                            orchestrationIntent: null,
                            timings,
                            directExecutorUsed: null,
                            delegateUsed: null,
                            pendingConfirmation: null,
                        });
                        await this.fireHook(this.config.lifecycleHooks?.afterMessage
                            ? () => this.config.lifecycleHooks.afterMessage(result)
                            : undefined);
                        return result;
                    }
                    // override — clear pending, continue normal flow
                    await this.config.pendingStateManager.clearPending(sessionId);
                }
            }
            // === Phase 1: Intent Resolution ===
            if (this.config.intentResolver) {
                const intentStart = Date.now();
                if (this.config.sessionStateStore && sessionId && cachedSessionState === undefined) {
                    cachedSessionState = await this.config.sessionStateStore.get(sessionId);
                }
                orchestrationIntent = await this.config.intentResolver.resolve({
                    message,
                    sessionState: cachedSessionState ?? undefined,
                });
                timings.intentResolution = Date.now() - intentStart;
            }
            // === Phase 2: Direct Execution ===
            if (this.config.directExecutors && orchestrationIntent) {
                const execStart = Date.now();
                for (const executor of this.config.directExecutors) {
                    if (executor.canHandle(orchestrationIntent)) {
                        const execResult = await executor.execute({
                            message,
                            intent: orchestrationIntent,
                            options: options,
                        });
                        if (execResult !== null) {
                            phaseReached = "direct_execution";
                            directExecutorUsed = executor.name;
                            timings.directExecution = Date.now() - execStart;
                            timings.total = Date.now() - startTime;
                            const result = buildFinalResult(execResult, {
                                phaseReached,
                                orchestrationIntent,
                                timings,
                                directExecutorUsed,
                                delegateUsed: null,
                            });
                            await this.fireHook(this.config.lifecycleHooks?.afterMessage
                                ? () => this.config.lifecycleHooks.afterMessage(result)
                                : undefined);
                            return result;
                        }
                    }
                }
            }
            // === Phase 3: Delegate Routing ===
            const delegateStart = Date.now();
            let selectedDelegate = this.config.delegate;
            let selectedDelegateName = "default";
            if (orchestrationIntent && this.config.delegates) {
                const mapped = this.config.delegates.get(orchestrationIntent.object);
                if (mapped) {
                    selectedDelegate = mapped;
                    selectedDelegateName = orchestrationIntent.object;
                }
            }
            // Enrich options with session state if available (use cached fetch)
            let enrichedOptions = options;
            if (this.config.sessionStateStore && sessionId) {
                if (cachedSessionState === undefined) {
                    cachedSessionState = await this.config.sessionStateStore.get(sessionId);
                }
                if (cachedSessionState) {
                    enrichedOptions = { ...options, sessionState: cachedSessionState };
                }
            }
            const delegateResult = await selectedDelegate.chat(message, enrichedOptions);
            timings.delegate = Date.now() - delegateStart;
            timings.total = Date.now() - startTime;
            phaseReached = "delegate";
            delegateUsed = selectedDelegateName;
            // Update session state if applicable (reuse cached session state)
            if (this.config.sessionStateStore && sessionId && delegateResult.sessionId) {
                const newState = {
                    sessionId,
                    lastPresentedEntities: cachedSessionState?.lastPresentedEntities ?? [],
                    metadata: cachedSessionState?.metadata ?? {},
                    updatedAt: Date.now(),
                };
                await this.config.sessionStateStore.save(sessionId, newState);
            }
            const result = buildFinalResult(delegateResult, {
                phaseReached,
                orchestrationIntent,
                timings,
                directExecutorUsed,
                delegateUsed,
                sessionId: sessionId ?? delegateResult.sessionId,
            });
            await this.fireHook(this.config.lifecycleHooks?.afterMessage
                ? () => this.config.lifecycleHooks.afterMessage(result)
                : undefined);
            return result;
        }
        catch (error) {
            // Fire onError hook
            await this.fireHook(this.config.lifecycleHooks?.onError
                ? () => this.config.lifecycleHooks.onError(error)
                : undefined);
            // Re-throw after hook
            throw error;
        }
    }
    /**
     * Process a channel-specific raw input through the channel adapter.
     */
    async processChannel(rawInput) {
        if (!this.config.channelAdapter) {
            throw new Error("No channelAdapter configured");
        }
        const channelMessage = this.config.channelAdapter.parseIncoming(rawInput);
        const result = await this.chat(channelMessage.text, channelMessage.options);
        return this.config.channelAdapter.formatOutgoing(result);
    }
}
exports.AgentOrchestrator = AgentOrchestrator;
