import type { BaseSummaryStore, CompressedSummary } from "./base.js";

export class InMemorySummaryStore implements BaseSummaryStore {
  private store = new Map<string, CompressedSummary>();

  async get(sessionId: string): Promise<CompressedSummary | null> {
    return this.store.get(sessionId) ?? null;
  }

  async save(sessionId: string, summary: CompressedSummary): Promise<void> {
    this.store.set(sessionId, summary);
  }

  async delete(sessionId: string): Promise<void> {
    this.store.delete(sessionId);
  }
}
