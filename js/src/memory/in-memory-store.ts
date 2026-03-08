import type { MemoryItem, MemoryStore } from "./base.js";
import { cosineSimilarity } from "../utils/math.js";

export class InMemoryMemoryStore implements MemoryStore {
  private items = new Map<string, { item: MemoryItem; embedding: number[] }>();

  async add(item: MemoryItem, embedding: number[]): Promise<void> {
    this.items.set(item.id, { item, embedding });
  }

  async search(
    userId: string,
    embedding: number[],
    topK = 5,
  ): Promise<MemoryItem[]> {
    const userItems = [...this.items.values()].filter(
      (x) => x.item.userId === userId,
    );

    return userItems
      .map((x) => ({
        item: x.item,
        score: cosineSimilarity(embedding, x.embedding),
      }))
      .sort((a, b) => b.score - a.score)
      .slice(0, topK)
      .map((x) => ({ ...x.item, score: x.score }));
  }

  async update(
    itemId: string,
    content: string,
    embedding: number[],
  ): Promise<void> {
    const existing = this.items.get(itemId);
    if (existing) {
      existing.item.content = content;
      existing.item.updatedAt = new Date();
      existing.embedding = embedding;
    }
  }

  async delete(itemId: string): Promise<void> {
    this.items.delete(itemId);
  }

  async getAll(userId: string): Promise<MemoryItem[]> {
    return [...this.items.values()]
      .filter((x) => x.item.userId === userId)
      .map((x) => x.item);
  }
}
