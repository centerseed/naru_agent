import { v4 as uuidv4 } from "uuid";
import type { NaruResult, ChatOptions } from "../types.js";
import type { OrchestrationResult } from "./result.js";
import type { AgentDecisionTrace, OrchestrationPhase, OrchestrationTimings } from "./trace.js";
import type { BaseIntentResolver, OrchestratorIntent } from "./intent.js";
import type { BaseDirectExecutor } from "./executor.js";
import type { BasePendingStateManager } from "./pending.js";
import type { AgentSessionState, BaseSessionStateStore } from "./session-state.js";
import type { ChannelAdapter, ChannelMessage } from "./channel.js";
import { classifyConfirmationDisposition } from "./pending.js";

/**
 * AgentChatDelegate — any object with a chat() method.
 * NaruAgent satisfies this structurally (duck typing).
 */
export interface AgentChatDelegate {
  chat(message: string, options?: ChatOptions): Promise<NaruResult>;
}

export interface LifecycleHooks {
  beforeMessage?: (message: string, options?: ChatOptions) => Promise<void> | void;
  afterMessage?: (result: OrchestrationResult) => Promise<void> | void;
  onError?: (error: unknown) => Promise<void> | void;
}

export interface AgentOrchestratorConfig<T extends string = string> {
  /** Default delegate (fallback) */
  delegate: AgentChatDelegate;
  /** Named delegates — keys are intent.object values */
  delegates?: Map<T, AgentChatDelegate>;
  /** Intent resolver (optional) */
  intentResolver?: BaseIntentResolver<T>;
  /** Direct executors (optional, tried in order) */
  directExecutors?: BaseDirectExecutor<T>[];
  /** Pending state manager for confirmation flows */
  pendingStateManager?: BasePendingStateManager;
  /** Session state store for entity tracking */
  sessionStateStore?: BaseSessionStateStore;
  /** Channel adapter for channel-specific I/O */
  channelAdapter?: ChannelAdapter;
  /** Lifecycle hooks */
  lifecycleHooks?: LifecycleHooks;
  /** Custom confirmation classifier */
  confirmationClassifier?: (message: string) => "confirm" | "reject" | "override";
}

/**
 * AgentOrchestrator — wraps one or more AgentChatDelegate instances with:
 *   Phase 0: Pending confirmation handling
 *   Phase 1: Intent resolution
 *   Phase 2: Direct execution (bypass LLM)
 *   Phase 3: Delegate routing
 *
 * AgentOrchestrator itself satisfies AgentChatDelegate, enabling nesting.
 */
export class AgentOrchestrator<T extends string = string>
  implements AgentChatDelegate {
  private config: AgentOrchestratorConfig<T>;

  constructor(config: AgentOrchestratorConfig<T>) {
    this.config = config;
  }

  private async fireHook(fn: (() => Promise<void> | void) | undefined): Promise<void> {
    if (fn) {
      try {
        await fn();
      } catch {
        // hooks do not affect main flow
      }
    }
  }

  async chat(
    message: string,
    options?: ChatOptions,
  ): Promise<OrchestrationResult> {
    const startTime = Date.now();
    const traceId = uuidv4();
    const sessionId = options?.sessionId ?? null;

    const timings: OrchestrationTimings = { total: 0 };
    let phaseReached: OrchestrationPhase = "delegate";
    let orchestrationIntent: OrchestratorIntent<T> | null = null;
    let directExecutorUsed: string | null = null;
    let delegateUsed: string | null = null;

    // Fire beforeMessage hook
    await this.fireHook(
      this.config.lifecycleHooks?.beforeMessage
        ? () => this.config.lifecycleHooks!.beforeMessage!(message, options)
        : undefined,
    );

    const buildDecisionTrace = (overrides: {
      phaseReached: OrchestrationPhase;
      orchestrationIntent: OrchestratorIntent<T> | null;
      timings: OrchestrationTimings;
      directExecutorUsed: string | null;
      delegateUsed: string | null;
    }): AgentDecisionTrace => ({
      traceId,
      phaseReached: overrides.phaseReached,
      intentResolved: overrides.orchestrationIntent as OrchestratorIntent<string> | null,
      timings: overrides.timings,
      directExecutorUsed: overrides.directExecutorUsed,
      delegateUsed: overrides.delegateUsed,
    });

    const buildFinalResult = (
      baseResult: NaruResult,
      overrides: {
        phaseReached: OrchestrationPhase;
        orchestrationIntent: OrchestratorIntent<T> | null;
        timings: OrchestrationTimings;
        directExecutorUsed: string | null;
        delegateUsed: string | null;
        pendingConfirmation?: { type: string; payload: Record<string, unknown> } | null;
        sessionId?: string | null;
        content?: string;
      },
    ): OrchestrationResult => {
      const decisionTrace = buildDecisionTrace(overrides);
      return {
        ...baseResult,
        content: overrides.content ?? baseResult.content,
        orchestrationIntent: overrides.orchestrationIntent as OrchestratorIntent<string> | null,
        decisionTrace,
        pendingConfirmation: overrides.pendingConfirmation ?? null,
        sessionId: overrides.sessionId !== undefined ? overrides.sessionId : (sessionId ?? baseResult.sessionId),
      };
    };

    // Cache session state to avoid triple fetch within the same chat() call
    let cachedSessionState: AgentSessionState | null | undefined;

    try {
      // === Phase 0: Pending Confirmation ===
      if (this.config.pendingStateManager && sessionId) {
        const pending = await this.config.pendingStateManager.getPending(sessionId);
        if (pending) {
          const classifier =
            this.config.confirmationClassifier ?? classifyConfirmationDisposition;
          const disposition = classifier(message);

          if (disposition === "confirm" || disposition === "reject") {
            // Handle confirmation/rejection
            await this.config.pendingStateManager.clearPending(sessionId);
            phaseReached = "pending_confirmation";
            timings.total = Date.now() - startTime;

            const confirmContent =
              disposition === "confirm"
                ? `Confirmed: ${pending.type}`
                : `Rejected: ${pending.type}`;

            const baseResult: NaruResult = {
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

            await this.fireHook(
              this.config.lifecycleHooks?.afterMessage
                ? () => this.config.lifecycleHooks!.afterMessage!(result)
                : undefined,
            );

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
              options: options as Record<string, unknown>,
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

              await this.fireHook(
                this.config.lifecycleHooks?.afterMessage
                  ? () => this.config.lifecycleHooks!.afterMessage!(result)
                  : undefined,
              );

              return result;
            }
          }
        }
      }

      // === Phase 3: Delegate Routing ===
      const delegateStart = Date.now();
      let selectedDelegate: AgentChatDelegate = this.config.delegate;
      let selectedDelegateName = "default";

      if (orchestrationIntent && this.config.delegates) {
        const mapped = this.config.delegates.get(orchestrationIntent.object as T);
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
          enrichedOptions = { ...options, sessionState: cachedSessionState } as ChatOptions & { sessionState: unknown };
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

      await this.fireHook(
        this.config.lifecycleHooks?.afterMessage
          ? () => this.config.lifecycleHooks!.afterMessage!(result)
          : undefined,
      );

      return result;
    } catch (error) {
      // Fire onError hook
      await this.fireHook(
        this.config.lifecycleHooks?.onError
          ? () => this.config.lifecycleHooks!.onError!(error)
          : undefined,
      );

      // Re-throw after hook
      throw error;
    }
  }

  /**
   * Process a channel-specific raw input through the channel adapter.
   */
  async processChannel<TIn, TOut>(rawInput: TIn): Promise<TOut> {
    if (!this.config.channelAdapter) {
      throw new Error("No channelAdapter configured");
    }

    const channelMessage: ChannelMessage =
      this.config.channelAdapter.parseIncoming(rawInput);

    const result = await this.chat(
      channelMessage.text,
      channelMessage.options,
    );

    return (this.config.channelAdapter as ChannelAdapter<TIn, TOut>).formatOutgoing(result) as TOut;
  }
}
