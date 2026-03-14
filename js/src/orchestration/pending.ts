/**
 * Pending state management — tracks confirmations awaiting user response.
 */

export interface PendingState {
  type: string;
  payload: Record<string, unknown>;
  createdAt: number;
}

export type ConfirmationDisposition = "confirm" | "reject" | "override";

export interface BasePendingStateManager {
  getPending(sessionId: string): Promise<PendingState | null>;
  setPending(sessionId: string, state: PendingState): Promise<void>;
  clearPending(sessionId: string): Promise<void>;
}

/**
 * InMemoryPendingStateManager — simple in-memory Map implementation.
 */
export class InMemoryPendingStateManager implements BasePendingStateManager {
  private store = new Map<string, PendingState>();

  async getPending(sessionId: string): Promise<PendingState | null> {
    return this.store.get(sessionId) ?? null;
  }

  async setPending(sessionId: string, state: PendingState): Promise<void> {
    this.store.set(sessionId, state);
  }

  async clearPending(sessionId: string): Promise<void> {
    this.store.delete(sessionId);
  }
}

const CONFIRM_PATTERN = /^(好|確認|對|yes|y|ok|好的|是|沒問題|sure|confirm)$/i;
const REJECT_PATTERN = /^(不要|取消|no|n|不|cancel|否|算了|不行|reject)$/i;

/**
 * Default implementation to classify a user message's disposition toward a pending confirmation.
 */
export function classifyConfirmationDisposition(
  message: string,
): ConfirmationDisposition {
  const trimmed = message.trim();
  if (CONFIRM_PATTERN.test(trimmed)) return "confirm";
  if (REJECT_PATTERN.test(trimmed)) return "reject";
  return "override";
}
