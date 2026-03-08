// Type declarations for optional peer dependencies
declare module "chromadb" {
  export class ChromaClient {
    constructor(config?: { path?: string });
    getOrCreateCollection(opts: { name: string; embeddingFunction?: unknown }): Promise<Collection>;
  }
  export interface Collection {
    add(params: { ids: string[]; documents: string[]; metadatas?: unknown[] }): Promise<void>;
    query(params: { queryTexts: string[]; nResults?: number }): Promise<{
      documents: (string | null)[][];
      distances: number[][];
      metadatas: (Record<string, unknown> | null)[][];
    }>;
  }
}

declare module "mem0ai" {
  export class MemoryClient {
    constructor(config: { apiKey: string });
    add(messages: unknown[], opts: Record<string, unknown>): Promise<unknown>;
    search(query: string, opts: Record<string, unknown>): Promise<unknown>;
    getAll(opts: Record<string, unknown>): Promise<unknown>;
  }
}
