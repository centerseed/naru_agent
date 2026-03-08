import type { ModelMessage } from "ai";

export interface BaseSessionStore {
  get(sessionId: string): Promise<ModelMessage[] | null>;
  save(sessionId: string, history: ModelMessage[]): Promise<void>;
  delete(sessionId: string): Promise<void>;
}
