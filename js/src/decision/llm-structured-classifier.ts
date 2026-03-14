import { generateObject, type LanguageModel } from "ai";
import type { z } from "zod";
import { normalizeUsage } from "../types.js";
import type {
  StructuredClassifier,
  StructuredClassifierInput,
  StructuredClassifierOutput,
} from "./types.js";

export interface LLMStructuredClassifierConfig<T> {
  name?: string;
  model: LanguageModel;
  schema: z.ZodType<T>;
  systemPrompt?: string;
}

export class LLMStructuredClassifier<T>
  implements StructuredClassifier<T>
{
  readonly name: string;
  private model: LanguageModel;
  private schema: z.ZodType<T>;
  private systemPrompt: string | undefined;

  constructor(config: LLMStructuredClassifierConfig<T>) {
    this.name = config.name ?? "LLMStructuredClassifier";
    this.model = config.model;
    this.schema = config.schema;
    this.systemPrompt = config.systemPrompt;
  }

  async classify(
    input: StructuredClassifierInput,
  ): Promise<StructuredClassifierOutput<T>> {
    const contextParts: string[] = [];

    if (input.summary) {
      contextParts.push(`【Conversation Summary】\n${input.summary}`);
    }
    if (input.memoryContext) {
      contextParts.push(`【User Memory】\n${input.memoryContext}`);
    }
    if (input.knowledgeContext) {
      contextParts.push(`【Knowledge】\n${input.knowledgeContext}`);
    }
    if (input.extraContext?.length) {
      contextParts.push(...input.extraContext);
    }

    const userPrompt = contextParts.length > 0
      ? `${contextParts.join("\n\n")}\n\n---\nUser message: ${input.message}`
      : input.message;

    const { object, usage } = await generateObject({
      model: this.model,
      schema: this.schema,
      system: this.systemPrompt,
      prompt: userPrompt,
    });

    return {
      result: object as T,
      rawText: JSON.stringify(object),
      usage: usage ? normalizeUsage(usage) : undefined,
    };
  }
}
