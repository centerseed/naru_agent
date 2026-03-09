"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.Mem0MemoryManager = void 0;
const base_js_1 = require("./base.js");
/**
 * Production memory manager backed by Mem0 (mem0ai).
 * Same public API as MemoryManager but delegates to Mem0's hosted service.
 * Requires `mem0ai` as a peer dependency.
 */
class Mem0MemoryManager {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    clientPromise = null;
    apiKey;
    organizationId;
    projectId;
    constructor(config) {
        this.apiKey = config.apiKey;
        this.organizationId = config.organizationId;
        this.projectId = config.projectId;
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    getClient() {
        if (!this.clientPromise) {
            this.clientPromise = (async () => {
                const mod = await Promise.resolve().then(() => __importStar(require("mem0ai")));
                const MemoryClient = mod.MemoryClient ?? mod.default;
                return new MemoryClient({ apiKey: this.apiKey });
            })();
        }
        return this.clientPromise;
    }
    baseParams(userId) {
        return {
            user_id: userId,
            ...(this.organizationId && { org_id: this.organizationId }),
            ...(this.projectId && { project_id: this.projectId }),
        };
    }
    /**
     * Add messages to Mem0. Mem0 handles fact extraction and reconciliation internally.
     */
    async add(userId, messages) {
        const client = await this.getClient();
        const result = await client.add(messages, {
            ...this.baseParams(userId),
        });
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const results = Array.isArray(result) ? result : result?.results ?? [];
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        return results.map((r) => this.toMemoryItem(r, userId));
    }
    async search(userId, query, topK = 5) {
        const client = await this.getClient();
        const result = await client.search(query, {
            ...this.baseParams(userId),
            limit: topK,
        });
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const results = Array.isArray(result) ? result : result?.results ?? [];
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        return results.map((r) => this.toMemoryItem(r, userId));
    }
    async getContextString(userId, query, topK = 5) {
        const memories = await this.search(userId, query, topK);
        return (0, base_js_1.formatMemoryContext)(memories);
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    toMemoryItem(raw, userId) {
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
exports.Mem0MemoryManager = Mem0MemoryManager;
