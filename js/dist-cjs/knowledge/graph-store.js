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
exports.GraphKnowledgeStore = void 0;
const base_js_1 = require("./base.js");
const ai_1 = require("ai");
const zod_1 = require("zod");
const EntityRelationSchema = zod_1.z.object({
    entities: zod_1.z.array(zod_1.z.object({
        name: zod_1.z.string(),
        type: zod_1.z.string(),
        description: zod_1.z.string().optional(),
    })),
    relations: zod_1.z.array(zod_1.z.object({
        source: zod_1.z.string(),
        target: zod_1.z.string(),
        relation: zod_1.z.string(),
    })),
});
/**
 * Knowledge graph store using graphology. Requires `graphology` as optional dependency.
 */
class GraphKnowledgeStore {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    graph = null;
    model;
    graphLib = null;
    constructor(config) {
        this.model = config.model;
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    async ensureGraph() {
        if (this.graph)
            return this.graph;
        const graphology = await Promise.resolve().then(() => __importStar(require("graphology")));
        this.graphLib = graphology;
        this.graph = new graphology.default();
        return this.graph;
    }
    async ingestText(text) {
        const graph = await this.ensureGraph();
        const { object } = await (0, ai_1.generateObject)({
            model: this.model,
            schema: EntityRelationSchema,
            prompt: `Extract entities and relationships from this text. Focus on key concepts, people, organizations, and their relationships.\n\n${text}`,
        });
        for (const entity of object.entities) {
            const key = entity.name.toLowerCase();
            if (!graph.hasNode(key)) {
                graph.addNode(key, {
                    label: entity.name,
                    type: entity.type,
                    description: entity.description ?? "",
                });
            }
        }
        for (const rel of object.relations) {
            const src = rel.source.toLowerCase();
            const tgt = rel.target.toLowerCase();
            if (graph.hasNode(src) && graph.hasNode(tgt)) {
                try {
                    graph.addEdge(src, tgt, { relation: rel.relation });
                }
                catch {
                    // edge may already exist
                }
            }
        }
        return { entities: object.entities.length, relations: object.relations.length };
    }
    async search(query, topK = 3) {
        const graph = await this.ensureGraph();
        const queryLower = query.toLowerCase();
        const results = [];
        // Find matching nodes
        const matchedNodes = [];
        graph.forEachNode((node, attrs) => {
            const label = attrs.label ?? node;
            if (queryLower.includes(node) ||
                queryLower.includes(label.toLowerCase())) {
                matchedNodes.push(node);
            }
        });
        // Expand neighbors for matched nodes
        for (const node of matchedNodes.slice(0, topK)) {
            const attrs = graph.getNodeAttributes(node);
            const neighbors = [];
            graph.forEachNeighbor(node, (neighbor) => {
                const nAttrs = graph.getNodeAttributes(neighbor);
                neighbors.push(nAttrs.label ?? neighbor);
            });
            const edges = [];
            graph.forEachEdge(node, (_edge, edgeAttrs, src, tgt) => {
                const srcLabel = graph.getNodeAttributes(src).label ?? src;
                const tgtLabel = graph.getNodeAttributes(tgt).label ?? tgt;
                edges.push(`${srcLabel} -[${edgeAttrs.relation}]-> ${tgtLabel}`);
            });
            const text = [
                `Entity: ${attrs.label} (${attrs.type})`,
                attrs.description ? `Description: ${attrs.description}` : "",
                edges.length > 0 ? `Relations:\n${edges.join("\n")}` : "",
            ]
                .filter(Boolean)
                .join("\n");
            results.push({
                text,
                score: 1.0,
                metadata: { nodeId: node, type: attrs.type },
            });
        }
        return results.slice(0, topK);
    }
    formatContext(results, minScore = 0.3) {
        return (0, base_js_1.formatKnowledgeContext)(results, minScore);
    }
    getGraph() {
        return this.graph;
    }
}
exports.GraphKnowledgeStore = GraphKnowledgeStore;
