/**
 * Generic intent types and resolvers for the orchestration layer.
 */

export type GenericIntentObject =
  | "greeting"
  | "query"
  | "action"
  | "confirmation"
  | "unknown";

export interface OrchestratorIntent<T extends string = GenericIntentObject> {
  object: T;
  confidence: number;
  requiresConfirmation?: boolean;
}

export interface IntentResolveInput {
  message: string;
  history?: unknown[];
  sessionState?: unknown;
}

export interface BaseIntentResolver<T extends string = GenericIntentObject> {
  resolve(input: IntentResolveInput): Promise<OrchestratorIntent<T>>;
}

export interface DeterministicPattern<T extends string = GenericIntentObject> {
  pattern: RegExp;
  intent: OrchestratorIntent<T>;
}

/**
 * DeterministicIntentResolver — fast pattern matching, no LLM calls.
 * Returns first matching pattern or unknown with confidence 0.
 */
export class DeterministicIntentResolver<T extends string = GenericIntentObject>
  implements BaseIntentResolver<T> {
  private patterns: DeterministicPattern<T>[];

  constructor(patterns: DeterministicPattern<T>[]) {
    this.patterns = patterns;
  }

  async resolve(input: IntentResolveInput): Promise<OrchestratorIntent<T>> {
    for (const entry of this.patterns) {
      if (entry.pattern.test(input.message)) {
        return entry.intent;
      }
    }
    return { object: "unknown" as T, confidence: 0 };
  }
}

/**
 * LLMFallbackIntentResolver — tries deterministic first, falls back to LLM classifier.
 */
export class LLMFallbackIntentResolver<T extends string = GenericIntentObject>
  implements BaseIntentResolver<T> {
  private primary: BaseIntentResolver<T>;
  private fallbackAgent: { chat(message: string): Promise<{ content: string }> };
  private parseResponse?: (content: string) => OrchestratorIntent<T>;

  constructor(config: {
    primary: BaseIntentResolver<T>;
    fallbackAgent: { chat(message: string): Promise<{ content: string }> };
    parseResponse?: (content: string) => OrchestratorIntent<T>;
  }) {
    this.primary = config.primary;
    this.fallbackAgent = config.fallbackAgent;
    this.parseResponse = config.parseResponse;
  }

  async resolve(input: IntentResolveInput): Promise<OrchestratorIntent<T>> {
    const primaryResult = await this.primary.resolve(input);

    if (primaryResult.object !== "unknown") {
      return primaryResult;
    }

    // Fallback to LLM
    const llmResponse = await this.fallbackAgent.chat(
      `Classify the intent of this message: "${input.message}". Return a JSON object with "object" (string) and "confidence" (number 0-1).`,
    );

    if (this.parseResponse) {
      return this.parseResponse(llmResponse.content);
    }

    // Default parsing
    try {
      const parsed = JSON.parse(llmResponse.content);
      return {
        object: (parsed.object ?? "unknown") as T,
        confidence: parsed.confidence ?? 0.5,
      };
    } catch {
      return { object: "unknown" as T, confidence: 0 };
    }
  }
}
