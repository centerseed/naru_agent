/**
 * AgentSessionState — tracks entities presented in the last response for coreference resolution.
 */

export interface AgentSessionState {
  sessionId: string;
  lastPresentedEntities: unknown[];
  metadata: Record<string, unknown>;
  updatedAt: number;
}

export interface BaseSessionStateStore {
  get(sessionId: string): Promise<AgentSessionState | null>;
  save(sessionId: string, state: AgentSessionState): Promise<void>;
  clear(sessionId: string): Promise<void>;
}

/**
 * InMemorySessionStateStore — simple in-memory Map implementation.
 */
export class InMemorySessionStateStore implements BaseSessionStateStore {
  private store = new Map<string, AgentSessionState>();

  async get(sessionId: string): Promise<AgentSessionState | null> {
    return this.store.get(sessionId) ?? null;
  }

  async save(sessionId: string, state: AgentSessionState): Promise<void> {
    this.store.set(sessionId, state);
  }

  async clear(sessionId: string): Promise<void> {
    this.store.delete(sessionId);
  }
}
