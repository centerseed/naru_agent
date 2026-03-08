import type { BaseSkill } from "./base.js";
import type { EmbedFn } from "../types.js";
import { cosineSimilarity } from "../utils/math.js";

export interface BaseSkillSelector {
  select(skills: BaseSkill[], message: string): Promise<BaseSkill[]>;
}

/**
 * Case-insensitive keyword matching on skill triggers.
 */
export class KeywordSkillSelector implements BaseSkillSelector {
  async select(skills: BaseSkill[], message: string): Promise<BaseSkill[]> {
    const lower = message.toLowerCase();
    return skills.filter(
      (s) =>
        s.alwaysActive ||
        s.triggers.some((t) => lower.includes(t.toLowerCase())),
    );
  }
}

/**
 * Embedding-based similarity matching for skill selection.
 */
export class EmbeddingSkillSelector implements BaseSkillSelector {
  private embedFn: EmbedFn;
  private topK: number;
  private similarityThreshold: number;
  private cachedEmbeddings: Map<string, number[]> | null = null;

  constructor(
    embedFn: EmbedFn,
    topK = 2,
    similarityThreshold = 0.45,
  ) {
    this.embedFn = embedFn;
    this.topK = topK;
    this.similarityThreshold = similarityThreshold;
  }

  async select(skills: BaseSkill[], message: string): Promise<BaseSkill[]> {
    const alwaysActive = skills.filter((s) => s.alwaysActive);
    const candidates = skills.filter((s) => !s.alwaysActive);
    if (candidates.length === 0) return alwaysActive;

    // Build skill description embeddings (cached)
    if (!this.cachedEmbeddings) {
      const descriptions = candidates.map(
        (s) => `${s.name}: ${s.description} ${s.triggers.join(" ")}`,
      );
      const embeddings = await this.embedFn(descriptions);
      this.cachedEmbeddings = new Map();
      for (let i = 0; i < candidates.length; i++) {
        this.cachedEmbeddings.set(candidates[i].name, embeddings[i]);
      }
    }

    const [queryEmbed] = await this.embedFn([message]);

    const scored = candidates
      .map((s) => ({
        skill: s,
        score: cosineSimilarity(queryEmbed, this.cachedEmbeddings!.get(s.name)!),
      }))
      .filter((x) => x.score >= this.similarityThreshold)
      .sort((a, b) => b.score - a.score)
      .slice(0, this.topK)
      .map((x) => x.skill);

    return [...alwaysActive, ...scored];
  }
}
