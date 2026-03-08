import type { BaseSkill, SkillContext, SkillResult } from "./base.js";
import type { BaseSkillSelector } from "./selectors.js";
import { KeywordSkillSelector } from "./selectors.js";
import { makeSkillResult } from "./base.js";

export class SkillRegistry {
  private skills: BaseSkill[];
  private selector: BaseSkillSelector;
  private maxActiveSkills: number;

  constructor(
    skills: BaseSkill[],
    selector?: BaseSkillSelector,
    maxActiveSkills = 3,
  ) {
    this.skills = skills;
    this.selector = selector ?? new KeywordSkillSelector();
    this.maxActiveSkills = maxActiveSkills;
  }

  async selectSkills(message: string): Promise<BaseSkill[]> {
    const selected = await this.selector.select(this.skills, message);
    return selected
      .sort((a, b) => b.priority - a.priority)
      .slice(0, this.maxActiveSkills);
  }

  async runSkills(
    message: string,
    context: SkillContext,
  ): Promise<SkillResult[]> {
    const selected = await this.selectSkills(message);
    if (selected.length === 0) return [];

    const results = await Promise.allSettled(
      selected.map(async (s) => {
        try {
          const result = await s.run(message, context);
          return { ...result, skillName: s.name };
        } catch {
          return makeSkillResult({ skillName: s.name, skipped: true });
        }
      }),
    );

    return results
      .filter(
        (r): r is PromiseFulfilledResult<SkillResult> =>
          r.status === "fulfilled",
      )
      .map((r) => r.value)
      .filter((r) => !r.skipped);
  }
}
