import { formatMemoryContext, type MemoryItem } from "./base.js";

interface Mem0Config {
  apiKey: string;
  organizationId?: string;
  projectId?: string;
}

/**
 * Production memory manager backed by Mem0 (mem0ai).
 * Same public API as MemoryManager but delegates to Mem0's hosted service.
 * Requires `mem0ai` as a peer dependency.
 */
export class Mem0MemoryManager {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private clientPromise: Promise<any> | null = null;
  private apiKey: string;
  private organizationId?: string;
  private projectId?: string;

  constructor(config: Mem0Config) {
    this.apiKey = config.apiKey;
    this.organizationId = config.organizationId;
    this.projectId = config.projectId;
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private getClient(): Promise<any> {
    if (!this.clientPromise) {
      this.clientPromise = (async () => {
        const mod = await import("mem0ai");
        const MemoryClient = mod.MemoryClient ?? mod.default;
        return new MemoryClient({ apiKey: this.apiKey });
      })();
    }
    return this.clientPromise;
  }

  private baseParams(userId: string) {
    return {
      user_id: userId,
      ...(this.organizationId && { org_id: this.organizationId }),
      ...(this.projectId && { project_id: this.projectId }),
    };
  }

  /**
   * Add messages to Mem0. Mem0 handles fact extraction and reconciliation internally.
   */
  async add(
    userId: string,
    messages: Array<{ role: string; content: string }>,
  ): Promise<MemoryItem[]> {
    const client = await this.getClient();
    const result = await client.add(messages, {
      ...this.baseParams(userId),
    });

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const results = Array.isArray(result) ? result : result?.results ?? [];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return results.map((r: any) => this.toMemoryItem(r, userId));
  }

  async search(
    userId: string,
    query: string,
    topK = 5,
  ): Promise<MemoryItem[]> {
    const client = await this.getClient();
    const result = await client.search(query, {
      ...this.baseParams(userId),
      limit: topK,
    });

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const results = Array.isArray(result) ? result : result?.results ?? [];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return results.map((r: any) => this.toMemoryItem(r, userId));
  }

  async getContextString(
    userId: string,
    query: string,
    topK = 5,
  ): Promise<string> {
    const memories = await this.search(userId, query, topK);
    return formatMemoryContext(memories);
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private toMemoryItem(raw: any, userId: string): MemoryItem {
    return {
      id: raw.id ?? raw.memory_id ?? "",
      userId,
      content: raw.memory ?? raw.text ?? raw.content ?? "",
      metadata: raw.metadata ?? {},
      score: raw.score,
      createdAt: raw.created_at ? new Date(raw.created_at) : new Date(),
      updatedAt: raw.updated_at ? new Date(raw.updated_at) : new Date(),
    };
  }
}
