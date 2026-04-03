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

/**
 * Select skills using an LLM for intent-based routing.
 *
 * Sends a structured prompt describing each skill's trigger and exclusion
 * conditions to the LLM, then parses the response to determine which skills
 * should be activated.
 *
 * @param chatFn - Async function that accepts a prompt string and returns the
 *   LLM's response string. Wrap any LLM client with an arrow function.
 *
 * @example
 * ```ts
 * const selector = new LLMSkillSelector(
 *   async (prompt) => await myLLMClient.chat(prompt)
 * );
 * ```
 */
export class LLMSkillSelector implements BaseSkillSelector {
  private chatFn: (prompt: string) => Promise<string>;

  constructor(chatFn: (prompt: string) => Promise<string>) {
    this.chatFn = chatFn;
  }

  async select(skills: BaseSkill[], message: string): Promise<BaseSkill[]> {
    const always = skills.filter((s) => s.alwaysActive);
    const candidates = skills.filter((s) => !s.alwaysActive);

    if (candidates.length === 0) return always;

    const prompt = this._buildPrompt(candidates, message);
    const response = await this.chatFn(prompt);
    const selectedNames = this._parseResponse(response);

    const nameSet = new Set(selectedNames);
    const selected = candidates.filter((s) => nameSet.has(s.name));
    return [...always, ...selected];
  }

  private _buildPrompt(candidates: BaseSkill[], message: string): string {
    const lines: string[] = [
      "You are a skill router. Given a user message, decide which skills should be activated.",
      "",
      "For each skill below, I provide:",
      "- name: the skill identifier",
      "- trigger_conditions: when this skill SHOULD be activated",
      "- exclusion_conditions: when this skill should NOT be activated",
      "- triggers: keyword hints (fallback if no conditions defined)",
      "",
      "Skills:",
    ];

    for (const s of candidates) {
      lines.push("---");
      lines.push(`name: ${s.name}`);
      if (s.triggerConditions.length > 0) {
        lines.push("trigger_conditions:");
        for (const cond of s.triggerConditions) {
          lines.push(`  - "${cond}"`);
        }
      }
      if (s.exclusionConditions.length > 0) {
        lines.push("exclusion_conditions:");
        for (const cond of s.exclusionConditions) {
          lines.push(`  - "${cond}"`);
        }
      }
      if (s.triggers.length > 0) {
        lines.push(`triggers: ${JSON.stringify(s.triggers)}`);
      }
    }

    lines.push(
      "---",
      "",
      `User message: "${message}"`,
      "",
      "Respond with ONLY a JSON array of skill names that should be activated.",
      "If no skills match, respond with [].",
      'Example: ["calendar", "reminder"]',
    );

    return lines.join("\n");
  }

  private _parseResponse(response: string): string[] {
    const trimmed = response.trim();

    // Try direct JSON parse
    try {
      const result = JSON.parse(trimmed);
      if (Array.isArray(result)) {
        return result.map(String);
      }
    } catch {
      // fall through to regex fallback
    }

    // Regex fallback: find a JSON array pattern
    const arrayMatch = trimmed.match(/\[([^\]]*)\]/);
    if (arrayMatch) {
      try {
        const result = JSON.parse(arrayMatch[0]);
        if (Array.isArray(result)) {
          return result.map(String);
        }
      } catch {
        // fall through to last resort
      }
    }

    // Last resort: extract all quoted strings
    const quoted = trimmed.match(/"([^"]+)"/g);
    if (quoted) {
      return quoted.map((s) => s.slice(1, -1));
    }

    return [];
  }
}
