import { describe, it, expect, vi } from "vitest";
import { InMemoryMemoryStore } from "./in-memory-store.js";

describe("InMemoryMemoryStore", () => {
  it("adds and searches memories", async () => {
    const store = new InMemoryMemoryStore();
    const embedding = [1, 0, 0];

    await store.add(
      {
        id: "1",
        userId: "user1",
        content: "Likes coffee",
        metadata: {},
        createdAt: new Date(),
        updatedAt: new Date(),
      },
      embedding,
    );

    const results = await store.search("user1", [1, 0, 0], 5);
    expect(results).toHaveLength(1);
    expect(results[0].content).toBe("Likes coffee");
  });

  it("updates memories", async () => {
    const store = new InMemoryMemoryStore();
    await store.add(
      {
        id: "1",
        userId: "user1",
        content: "Likes coffee",
        metadata: {},
        createdAt: new Date(),
        updatedAt: new Date(),
      },
      [1, 0, 0],
    );

    await store.update("1", "Likes tea", [0, 1, 0]);
    const all = await store.getAll("user1");
    expect(all[0].content).toBe("Likes tea");
  });

  it("deletes memories", async () => {
    const store = new InMemoryMemoryStore();
    await store.add(
      {
        id: "1",
        userId: "user1",
        content: "test",
        metadata: {},
        createdAt: new Date(),
        updatedAt: new Date(),
      },
      [1, 0, 0],
    );

    await store.delete("1");
    const all = await store.getAll("user1");
    expect(all).toHaveLength(0);
  });
});
