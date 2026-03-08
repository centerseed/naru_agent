export interface KnowledgeResult {
  text: string;
  score: number;
  metadata: Record<string, unknown>;
}

export interface BaseKnowledgeStore {
  search(query: string, topK?: number): Promise<KnowledgeResult[]>;

  formatContext(results: KnowledgeResult[], minScore?: number): string;
}

/**
 * Default formatContext implementation.
 */
export function formatKnowledgeContext(
  results: KnowledgeResult[],
  minScore = 0.3,
): string {
  const filtered = results.filter((r) => r.score >= minScore);
  if (filtered.length === 0) return "";
  return filtered.map((r) => r.text).join("\n\n---\n\n");
}
