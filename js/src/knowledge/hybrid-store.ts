import type { BaseKnowledgeStore, KnowledgeResult } from "./base.js";
import { formatKnowledgeContext } from "./base.js";

/**
 * Multi-source knowledge store that merges results from multiple stores
 * with weighted scoring.
 */
export class HybridKnowledgeStore implements BaseKnowledgeStore {
  private stores: BaseKnowledgeStore[];
  private weights: number[];

  constructor(config: {
    stores: BaseKnowledgeStore[];
    weights?: number[];
  }) {
    this.stores = config.stores;
    this.weights =
      config.weights ?? config.stores.map(() => 1 / config.stores.length);
  }

  async search(query: string, topK = 3): Promise<KnowledgeResult[]> {
    const allResults = await Promise.allSettled(
      this.stores.map((store, i) =>
        store.search(query, topK).then((results) =>
          results.map((r) => ({
            ...r,
            score: r.score * this.weights[i],
          })),
        ),
      ),
    );

    const merged: KnowledgeResult[] = [];
    const seen = new Set<string>();

    for (const result of allResults) {
      if (result.status === "fulfilled") {
        for (const r of result.value) {
          // Deduplicate by text content
          const key = r.text.slice(0, 100);
          if (!seen.has(key)) {
            seen.add(key);
            merged.push(r);
          }
        }
      }
    }

    return merged.sort((a, b) => b.score - a.score).slice(0, topK);
  }

  formatContext(results: KnowledgeResult[], minScore = 0.3): string {
    return formatKnowledgeContext(results, minScore);
  }
}
