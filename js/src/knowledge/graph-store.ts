import type { BaseKnowledgeStore, KnowledgeResult } from "./base.js";
import { formatKnowledgeContext } from "./base.js";
import { generateObject, type LanguageModel } from "ai";
import { z } from "zod";

const EntityRelationSchema = z.object({
  entities: z.array(
    z.object({
      name: z.string(),
      type: z.string(),
      description: z.string().optional(),
    }),
  ),
  relations: z.array(
    z.object({
      source: z.string(),
      target: z.string(),
      relation: z.string(),
    }),
  ),
});

type GraphLib = typeof import("graphology");

/**
 * Knowledge graph store using graphology. Requires `graphology` as optional dependency.
 */
export class GraphKnowledgeStore implements BaseKnowledgeStore {
  private graph: InstanceType<GraphLib["default"]> | null = null;
  private model: LanguageModel;
  private graphLib: GraphLib | null = null;

  constructor(config: { model: LanguageModel }) {
    this.model = config.model;
  }

  private async ensureGraph(): Promise<InstanceType<GraphLib["default"]>> {
    if (this.graph) return this.graph;
    const graphology = await import("graphology");
    this.graphLib = graphology;
    this.graph = new graphology.default();
    return this.graph;
  }

  async ingestText(text: string): Promise<{ entities: number; relations: number }> {
    const graph = await this.ensureGraph();

    const { object } = await generateObject({
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
        } catch {
          // edge may already exist
        }
      }
    }

    return { entities: object.entities.length, relations: object.relations.length };
  }

  async search(query: string, topK = 3): Promise<KnowledgeResult[]> {
    const graph = await this.ensureGraph();
    const queryLower = query.toLowerCase();
    const results: KnowledgeResult[] = [];

    // Find matching nodes
    const matchedNodes: string[] = [];
    graph.forEachNode((node: string, attrs: Record<string, unknown>) => {
      const label = (attrs.label as string) ?? node;
      if (
        queryLower.includes(node) ||
        queryLower.includes(label.toLowerCase())
      ) {
        matchedNodes.push(node);
      }
    });

    // Expand neighbors for matched nodes
    for (const node of matchedNodes.slice(0, topK)) {
      const attrs = graph.getNodeAttributes(node);
      const neighbors: string[] = [];

      graph.forEachNeighbor(node, (neighbor: string) => {
        const nAttrs = graph.getNodeAttributes(neighbor);
        neighbors.push((nAttrs.label as string) ?? neighbor);
      });

      const edges: string[] = [];
      graph.forEachEdge(
        node,
        (_edge: string, edgeAttrs: Record<string, unknown>, src: string, tgt: string) => {
          const srcLabel =
            (graph.getNodeAttributes(src).label as string) ?? src;
          const tgtLabel =
            (graph.getNodeAttributes(tgt).label as string) ?? tgt;
          edges.push(
            `${srcLabel} -[${edgeAttrs.relation}]-> ${tgtLabel}`,
          );
        },
      );

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
        metadata: { nodeId: node, type: attrs.type as string },
      });
    }

    return results.slice(0, topK);
  }

  formatContext(results: KnowledgeResult[], minScore = 0.3): string {
    return formatKnowledgeContext(results, minScore);
  }

  getGraph(): unknown {
    return this.graph;
  }
}
