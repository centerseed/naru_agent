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
exports.ChromaKnowledgeStore = void 0;
const base_js_1 = require("./base.js");
/**
 * Knowledge store backed by ChromaDB.
 * Requires `chromadb` as a peer dependency.
 * Uses lazy initialization — the collection is created on first use.
 */
class ChromaKnowledgeStore {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    client = null;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    collectionPromise = null;
    collectionName;
    chromaUrl;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    embeddingFunction;
    constructor(config = {}) {
        this.chromaUrl = config.chromaUrl ?? "http://localhost:8000";
        this.collectionName = config.collectionName ?? "knowledge";
        this.embeddingFunction = config.embeddingFunction;
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    getCollection() {
        if (!this.collectionPromise) {
            this.collectionPromise = (async () => {
                const { ChromaClient } = await Promise.resolve().then(() => __importStar(require("chromadb")));
                this.client = new ChromaClient({ path: this.chromaUrl });
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                const opts = { name: this.collectionName };
                if (this.embeddingFunction) {
                    opts.embeddingFunction = this.embeddingFunction;
                }
                return this.client.getOrCreateCollection(opts);
            })();
        }
        return this.collectionPromise;
    }
    async ingest(text, metadata) {
        await this.batchIngest([text], metadata ? [metadata] : undefined);
    }
    async batchIngest(texts, metadataList) {
        const collection = await this.getCollection();
        const ids = texts.map(() => crypto.randomUUID());
        await collection.add({
            ids,
            documents: texts,
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            metadatas: metadataList,
        });
    }
    async search(query, topK = 3) {
        const collection = await this.getCollection();
        const results = await collection.query({
            queryTexts: [query],
            nResults: topK,
        });
        const documents = results.documents?.[0] ?? [];
        const distances = results.distances?.[0] ?? [];
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const metadatas = results.metadatas?.[0] ?? [];
        return documents.map((doc, i) => ({
            text: doc ?? "",
            score: 1 - (distances[i] ?? 1),
            metadata: metadatas[i] ?? {},
        }));
    }
    formatContext(results, minScore = 0.3) {
        return (0, base_js_1.formatKnowledgeContext)(results, minScore);
    }
}
exports.ChromaKnowledgeStore = ChromaKnowledgeStore;
