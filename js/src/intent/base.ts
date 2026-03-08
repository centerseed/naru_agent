import type { IntentResult } from "../types.js";
import type { BaseTool } from "../tools/base.js";

export type { IntentResult };

export interface BaseIntentClassifier {
  classify(message: string): Promise<IntentResult>;
}

export interface ToolCallingResult {
  toolResults: Array<{ tool: string; args: Record<string, unknown>; result: string }>;
  usage: Record<string, number>;
  rawResponse: string;
}

export interface BaseToolCallingClassifier {
  classify(message: string, tools: BaseTool[]): Promise<ToolCallingResult>;
}
