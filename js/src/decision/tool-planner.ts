import {
  generateText,
  stepCountIs,
  type LanguageModel,
} from "ai";
import type { BaseTool } from "../tools/base.js";
import { toVercelToolsNoop } from "../tools/vercel-adapter.js";
import type { ToolPlan } from "./types.js";

export interface ToolPlannerConfig {
  model: LanguageModel;
  systemPrompt?: string;
}

export class ToolPlanner {
  private model: LanguageModel;
  private systemPrompt: string | undefined;

  constructor(config: ToolPlannerConfig) {
    this.model = config.model;
    this.systemPrompt = config.systemPrompt;
  }

  async plan(message: string, tools: BaseTool[]): Promise<ToolPlan[]> {
    if (tools.length === 0) return [];

    const result = await generateText({
      model: this.model,
      system:
        this.systemPrompt ??
        "You are a tool planner. Given the user message, decide which tools to call and with what arguments. Call the appropriate tools.",
      prompt: message,
      tools: toVercelToolsNoop(tools),
      toolChoice: "auto",
      stopWhen: stepCountIs(1),
    });

    const plans: ToolPlan[] = [];
    for (const step of result.steps ?? []) {
      for (const tc of step.toolCalls ?? []) {
        plans.push({
          tool: tc.toolName,
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          args: (tc as any).args as Record<string, unknown>,
        });
      }
    }

    return plans;
  }
}
