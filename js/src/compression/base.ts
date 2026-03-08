export interface CompressedSummary {
  summaryText: string;
  compressedThroughRound: number;
  createdAt: number;
  modelUsed: string;
}

export interface BaseSummaryStore {
  get(sessionId: string): Promise<CompressedSummary | null>;
  save(sessionId: string, summary: CompressedSummary): Promise<void>;
  delete(sessionId: string): Promise<void>;
}
