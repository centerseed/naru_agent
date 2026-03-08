import type { BaseKnowledgeStore, KnowledgeResult } from "./base.js";
import { formatKnowledgeContext } from "./base.js";

export interface ChromaKnowledgeStoreConfig {
  collectionName?: string;
  chromaUrl?: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  embeddingFunction?: any;
}

/**
 * Knowledge store backed by ChromaDB.
 * Requires `chromadb` as a peer dependency.
 * Uses lazy initialization — the collection is created on first use.
 */
export class ChromaKnowledgeStore implements BaseKnowledgeStore {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private client: any = null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private collectionPromise: Promise<any> | null = null;
  private collectionName: string;
  private chromaUrl: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private embeddingFunction: any;

  constructor(config: ChromaKnowledgeStoreConfig = {}) {
    this.chromaUrl = config.chromaUrl ?? "http://localhost:8000";
    this.collectionName = config.collectionName ?? "knowledge";
    this.embeddingFunction = config.embeddingFunction;
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private getCollection(): Promise<any> {
    if (!this.collectionPromise) {
      this.collectionPromise = (async () => {
        const { ChromaClient } = await import("chromadb");
        this.client = new ChromaClient({ path: this.chromaUrl });
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const opts: any = { name: this.collectionName };
        if (this.embeddingFunction) {
          opts.embeddingFunction = this.embeddingFunction;
        }
        return this.client.getOrCreateCollection(opts);
      })();
    }
    return this.collectionPromise;
  }

  async ingest(text: string, metadata?: Record<string, unknown>): Promise<void> {
    await this.batchIngest([text], metadata ? [metadata] : undefined);
  }

  async batchIngest(
    texts: string[],
    metadataList?: Array<Record<string, unknown>>,
  ): Promise<void> {
    const collection = await this.getCollection();
    const ids = texts.map(() => crypto.randomUUID());
    await collection.add({
      ids,
      documents: texts,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      metadatas: metadataList as any,
    });
  }

  async search(query: string, topK = 3): Promise<KnowledgeResult[]> {
    const collection = await this.getCollection();
    const results = await collection.query({
      queryTexts: [query],
      nResults: topK,
    });

    const documents: string[] = results.documents?.[0] ?? [];
    const distances: number[] = results.distances?.[0] ?? [];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const metadatas: any[] = results.metadatas?.[0] ?? [];

    return documents.map((doc: string, i: number) => ({
      text: doc ?? "",
      score: 1 - (distances[i] ?? 1),
      metadata: (metadatas[i] as Record<string, unknown>) ?? {},
    }));
  }

  formatContext(results: KnowledgeResult[], minScore = 0.3): string {
    return formatKnowledgeContext(results, minScore);
  }
}
