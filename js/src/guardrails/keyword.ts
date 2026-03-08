import type { BaseGuardrail, GuardrailResult } from "./base.js";

export class KeywordGuardrail implements BaseGuardrail {
  private patterns: RegExp[];
  private inputMessage: string;
  private outputReplacement: string | null;

  constructor(config: {
    blockedPatterns: string[];
    inputMessage?: string;
    outputReplacement?: string | null;
    caseSensitive?: boolean;
  }) {
    const flags = config.caseSensitive ? "" : "i";
    this.patterns = config.blockedPatterns.map((p) => new RegExp(p, flags));
    this.inputMessage =
      config.inputMessage ?? "This request cannot be processed.";
    this.outputReplacement = config.outputReplacement ?? null;
  }

  async checkInput(message: string): Promise<GuardrailResult> {
    for (const pattern of this.patterns) {
      if (pattern.test(message)) {
        return {
          passed: false,
          modifiedText: null,
          reason: this.inputMessage,
        };
      }
    }
    return { passed: true, modifiedText: null, reason: null };
  }

  async checkOutput(response: string): Promise<GuardrailResult> {
    for (const pattern of this.patterns) {
      if (pattern.test(response)) {
        return {
          passed: false,
          modifiedText: this.outputReplacement,
          reason: `Output matched blocked pattern: ${pattern.source}`,
        };
      }
    }
    return { passed: true, modifiedText: null, reason: null };
  }
}
