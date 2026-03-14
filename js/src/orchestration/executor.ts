import type { OrchestratorIntent } from "./intent.js";
import type { OrchestrationResult } from "./result.js";

/**
 * BaseDirectExecutor — handles intents without calling the delegate LLM agent.
 * Return null to fallthrough to the next executor or delegate.
 */
export interface BaseDirectExecutor<T extends string = string> {
  /** Human-readable name for this executor (used in trace) */
  readonly name: string;
  /** Return true if this executor can handle the given intent */
  canHandle(intent: OrchestratorIntent<T>): boolean;
  /** Execute and return a result, or null to fallthrough */
  execute(input: {
    message: string;
    intent: OrchestratorIntent<T>;
    options?: Record<string, unknown>;
  }): Promise<OrchestrationResult | null>;
}
