import type { OrchestratorIntent } from "./intent.js";

/**
 * AgentDecisionTrace — records the decision path and timings for each orchestrator invocation.
 */
export type OrchestrationPhase =
  | "pending_confirmation"
  | "direct_execution"
  | "delegate"
  | "blocked";

export interface OrchestrationTimings {
  total: number;
  intentResolution?: number;
  directExecution?: number;
  delegate?: number;
}

export interface AgentDecisionTrace {
  traceId: string;
  phaseReached: OrchestrationPhase;
  intentResolved: OrchestratorIntent<string> | null;
  timings: OrchestrationTimings;
  directExecutorUsed: string | null;
  delegateUsed: string | null;
}
