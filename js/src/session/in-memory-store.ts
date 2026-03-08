import type { ModelMessage } from "ai";
import type { BaseSessionStore } from "./base.js";

export class InMemorySessionStore implements BaseSessionStore {
  private store = new Map<string, ModelMessage[]>();

  async get(sessionId: string): Promise<ModelMessage[] | null> {
    return this.store.get(sessionId) ?? null;
  }

  async save(sessionId: string, history: ModelMessage[]): Promise<void> {
    this.store.set(sessionId, history);
  }

  async delete(sessionId: string): Promise<void> {
    this.store.delete(sessionId);
  }
}
