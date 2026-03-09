"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.LLMMemoryManager = exports.MemoryManager = void 0;
const ai_1 = require("ai");
const zod_1 = require("zod");
const uuid_1 = require("uuid");
const base_js_1 = require("./base.js");
const FactExtractionSchema = zod_1.z.object({
    facts: zod_1.z.array(zod_1.z.string()).describe("Extracted factual statements"),
});
const ReconciliationActionSchema = zod_1.z.object({
    actions: zod_1.z.array(zod_1.z.object({
        fact: zod_1.z.string(),
        action: zod_1.z.enum(["ADD", "UPDATE", "DELETE", "NONE"]),
        targetId: zod_1.z.string().nullable().optional(),
        updatedText: zod_1.z.string().nullable().optional(),
    })),
});
/**
 * @deprecated Use Mem0MemoryManager for production.
 */
class MemoryManager {
    model;
    store;
    embedFn;
    reconciliationTopK;
    constructor(config) {
        this.model = config.model;
        this.store = config.store;
        this.embedFn = config.embedFn;
        this.reconciliationTopK = config.reconciliationTopK ?? 3;
    }
    /**
     * Extract facts from messages and reconcile with existing memories.
     */
    async add(userId, messages) {
        // Step 1: Extract facts
        const conversationText = messages
            .map((m) => `${m.role}: ${m.content}`)
            .join("\n");
        const { object: extracted } = await (0, ai_1.generateObject)({
            model: this.model,
            schema: FactExtractionSchema,
            prompt: `Extract factual statements about the user from this conversation. Only extract concrete facts, preferences, or personal information.\n\n${conversationText}`,
        });
        if (extracted.facts.length === 0)
            return [];
        // Step 2: Find similar existing memories for reconciliation (parallel)
        const factEmbeddings = await this.embedFn(extracted.facts);
        const searchResults = await Promise.all(factEmbeddings.map((embedding) => this.store.search(userId, embedding, this.reconciliationTopK)));
        const seenIds = new Set();
        const existingMemories = [];
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
        const { object: reconciliation } = await (0, ai_1.generateObject)({
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
        const added = [];
        await Promise.all(reconciliation.actions.map(async (action) => {
            switch (action.action) {
                case "ADD": {
                    const [embedding] = await this.embedFn([action.fact]);
                    const item = {
                        id: (0, uuid_1.v4)(),
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
        }));
        return added;
    }
    async search(userId, query, topK = 5) {
        const [embedding] = await this.embedFn([query]);
        return this.store.search(userId, embedding, topK);
    }
    async getContextString(userId, query, topK = 5) {
        const memories = await this.search(userId, query, topK);
        return (0, base_js_1.formatMemoryContext)(memories);
    }
}
exports.MemoryManager = MemoryManager;
exports.LLMMemoryManager = MemoryManager;
