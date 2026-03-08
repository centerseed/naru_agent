import { generateObject, type LanguageModel } from "ai";
import { z } from "zod";
import { v4 as uuidv4 } from "uuid";
import type { MemoryItem, MemoryStore } from "./base.js";
import type { EmbedFn } from "../types.js";

const FactExtractionSchema = z.object({
  facts: z.array(z.string()).describe("Extracted factual statements"),
});

const ReconciliationActionSchema = z.object({
  actions: z.array(
    z.object({
      fact: z.string(),
      action: z.enum(["ADD", "UPDATE", "DELETE", "NONE"]),
      targetId: z.string().nullable().optional(),
      updatedText: z.string().nullable().optional(),
    }),
  ),
});

export class MemoryManager {
  private model: LanguageModel;
  private store: MemoryStore;
  private embedFn: EmbedFn;
  private reconciliationTopK: number;

  constructor(config: {
    model: LanguageModel;
    store: MemoryStore;
    embedFn: EmbedFn;
    reconciliationTopK?: number;
  }) {
    this.model = config.model;
    this.store = config.store;
    this.embedFn = config.embedFn;
    this.reconciliationTopK = config.reconciliationTopK ?? 3;
  }

  /**
   * Extract facts from messages and reconcile with existing memories.
   */
  async add(
    userId: string,
    messages: Array<{ role: string; content: string }>,
  ): Promise<MemoryItem[]> {
    // Step 1: Extract facts
    const conversationText = messages
      .map((m) => `${m.role}: ${m.content}`)
      .join("\n");

    const { object: extracted } = await generateObject({
      model: this.model,
      schema: FactExtractionSchema,
      prompt: `Extract factual statements about the user from this conversation. Only extract concrete facts, preferences, or personal information.\n\n${conversationText}`,
    });

    if (extracted.facts.length === 0) return [];

    // Step 2: Find similar existing memories for reconciliation (parallel)
    const factEmbeddings = await this.embedFn(extracted.facts);
    const searchResults = await Promise.all(
      factEmbeddings.map((embedding) =>
        this.store.search(userId, embedding, this.reconciliationTopK),
      ),
    );

    const seenIds = new Set<string>();
    const existingMemories: MemoryItem[] = [];
    for (const results of searchResults) {
      for (const r of results) {
        if (!seenIds.has(r.id)) {
          seenIds.add(r.id);
          existingMemories.push(r);
        }
      }
    }

    // Step 3: Reconcile
    const existingStr = existingMemories
      .map((m) => `[${m.id}] ${m.content}`)
      .join("\n");

    const { object: reconciliation } = await generateObject({
      model: this.model,
      schema: ReconciliationActionSchema,
      prompt: [
        "Given new facts and existing memories, decide what to do with each fact.",
        "Actions: ADD (new fact), UPDATE (modify existing, provide targetId + updatedText), DELETE (remove outdated, provide targetId), NONE (already exists).",
        "",
        `New facts:\n${extracted.facts.map((f, i) => `${i + 1}. ${f}`).join("\n")}`,
        "",
        existingStr
          ? `Existing memories:\n${existingStr}`
          : "No existing memories.",
      ].join("\n"),
    });

    // Step 4: Execute actions (parallel)
    const added: MemoryItem[] = [];

    await Promise.all(
      reconciliation.actions.map(async (action) => {
        switch (action.action) {
          case "ADD": {
            const [embedding] = await this.embedFn([action.fact]);
            const item: MemoryItem = {
              id: uuidv4(),
              userId,
              content: action.fact,
              metadata: {},
              createdAt: new Date(),
              updatedAt: new Date(),
            };
            await this.store.add(item, embedding);
            added.push(item);
            break;
          }
          case "UPDATE": {
            if (action.targetId && action.updatedText) {
              const [embedding] = await this.embedFn([action.updatedText]);
              await this.store.update(action.targetId, action.updatedText, embedding);
            }
            break;
          }
          case "DELETE": {
            if (action.targetId) {
              await this.store.delete(action.targetId);
            }
            break;
          }
        }
      }),
    );

    return added;
  }

  async search(
    userId: string,
    query: string,
    topK = 5,
  ): Promise<MemoryItem[]> {
    const [embedding] = await this.embedFn([query]);
    return this.store.search(userId, embedding, topK);
  }

  async getContextString(
    userId: string,
    query: string,
    topK = 5,
  ): Promise<string> {
    const memories = await this.search(userId, query, topK);
    if (memories.length === 0) return "";
    return (
      "User memories:\n" +
      memories.map((m) => `- ${m.content}`).join("\n")
    );
  }
}
