import type { BaseTool } from "../tools/base.js";
import type { BaseKnowledgeStore } from "../knowledge/base.js";

export interface SkillContext {
  message: string;
  userId?: string;
  sessionId?: string;
  memoryContext: string;
  knowledgeStore?: BaseKnowledgeStore;
}

export interface SkillResult {
  promptInjection: string;
  extraTools: BaseTool[];
  overrideSystemPrompt: string | null;
  skillName: string;
  skipped: boolean;
}

export interface BaseSkill {
  name: string;
  description: string;
  triggers: string[];
  priority: number;
  alwaysActive: boolean;
  run: (message: string, context: SkillContext) => Promise<SkillResult>;
}

export interface SkillConfig {
  name: string;
  description?: string;
  triggers?: string[];
  priority?: number;
  alwaysActive?: boolean;
  run: (message: string, context: SkillContext) => Promise<SkillResult>;
}

/**
 * Factory function to create a skill (equivalent to Python @skill decorator).
 */
export function skill(config: SkillConfig): BaseSkill {
  return {
    name: config.name,
    description: config.description ?? "",
    triggers: config.triggers ?? [],
    priority: config.priority ?? 0,
    alwaysActive: config.alwaysActive ?? false,
    run: config.run,
  };
}

export function makeSkillResult(
  partial?: Partial<SkillResult>,
): SkillResult {
  return {
    promptInjection: "",
    extraTools: [],
    overrideSystemPrompt: null,
    skillName: "",
    skipped: false,
    ...partial,
  };
}
