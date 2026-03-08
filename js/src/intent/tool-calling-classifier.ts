import { generateText, stepCountIs, type LanguageModel } from "ai";
import type { BaseToolCallingClassifier, ToolCallingResult } from "./base.js";
import type { BaseTool } from "../tools/base.js";
import { toVercelTools } from "../tools/vercel-adapter.js";

/**
 * Uses a lightweight LLM to decide which tools to call, then executes them.
 */
export class LLMToolCallingClassifier implements BaseToolCallingClassifier {
  private model: LanguageModel;
  private systemPrompt: string;

  constructor(config: {
    model: LanguageModel;
    systemPrompt?: string;
  }) {
    this.model = config.model;
    this.systemPrompt =
      config.systemPrompt ??
      "You are a tool-calling assistant. Use the available tools to answer the user's question. Only call tools that are relevant.";
  }

  async classify(
    message: string,
    tools: BaseTool[],
  ): Promise<ToolCallingResult> {
    if (tools.length === 0) {
      return { toolResults: [], usage: {}, rawResponse: "" };
    }

    const vercelTools = toVercelTools(tools);

    const result = await generateText({
      model: this.model,
      system: this.systemPrompt,
      prompt: message,
      tools: vercelTools,
      stopWhen: stepCountIs(1),
    });

    const toolResults: ToolCallingResult["toolResults"] = [];
    // Extract tool call results from steps
    for (const step of result.steps ?? []) {
      for (const tc of step.toolCalls ?? []) {
        toolResults.push({
          tool: tc.toolName,
          args: (tc as unknown as { input: Record<string, unknown> }).input ?? {},
          result: "",
        });
      }
      // Match tool results by index
      const stepToolResults = (step as unknown as { toolResults?: Array<{ result: unknown }> }).toolResults ?? [];
      for (let i = 0; i < stepToolResults.length && i < toolResults.length; i++) {
        toolResults[toolResults.length - (stepToolResults.length - i)] = {
          ...toolResults[toolResults.length - (stepToolResults.length - i)],
          result: String(stepToolResults[i].result),
        };
      }
    }

    return {
      toolResults,
      usage: {
        promptTokens: result.usage?.inputTokens ?? 0,
        completionTokens: result.usage?.outputTokens ?? 0,
      },
      rawResponse: result.text,
    };
  }
}
