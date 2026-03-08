export interface MemoryItem {
  id: string;
  userId: string;
  content: string;
  metadata: Record<string, unknown>;
  score?: number;
  createdAt: Date;
  updatedAt: Date;
}

export interface MemoryStore {
  add(item: MemoryItem, embedding: number[]): Promise<void>;
  search(userId: string, embedding: number[], topK?: number): Promise<MemoryItem[]>;
  update(itemId: string, content: string, embedding: number[]): Promise<void>;
  delete(itemId: string): Promise<void>;
  getAll(userId: string): Promise<MemoryItem[]>;
}
