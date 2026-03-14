import type { NaruResult } from "../types.js";
import type { AgentDecisionTrace } from "./trace.js";
import type { OrchestratorIntent } from "./intent.js";

export interface PendingConfirmation {
  type: string;
  payload: Record<string, unknown>;
}

/**
 * OrchestrationResult extends NaruResult with orchestration-specific fields.
 * All new fields are optional or have reasonable defaults.
 *
 * Note: `trace` from NaruResult (Trace | null) is preserved for backward compat.
 * The orchestration decision trace is exposed via `decisionTrace`.
 * The orchestration-resolved intent is exposed via `orchestrationIntent`.
 */
export interface OrchestrationResult extends NaruResult {
  /** Full decision trace for this orchestration invocation */
  decisionTrace: AgentDecisionTrace;
  /** If set, agent is waiting for user confirmation */
  pendingConfirmation: PendingConfirmation | null;
  /** The orchestration-resolved intent (null if no resolver configured) */
  orchestrationIntent: OrchestratorIntent<string> | null;
}
