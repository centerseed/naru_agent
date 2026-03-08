import { generateText, type LanguageModel, type ModelMessage } from "ai";
import type { BaseSummaryStore, CompressedSummary } from "./base.js";

export class ContextCompressor {
  private summaryStore: BaseSummaryStore;
  private summaryModel: LanguageModel;
  private keepLastRounds: number;
  private thresholdRounds: number;

  constructor(config: {
    summaryStore: BaseSummaryStore;
    summaryModel: LanguageModel;
    keepLastRounds?: number;
    thresholdRounds?: number;
  }) {
    this.summaryStore = config.summaryStore;
    this.summaryModel = config.summaryModel;
    this.keepLastRounds = config.keepLastRounds ?? 5;
    this.thresholdRounds = config.thresholdRounds ?? 5;
  }

  async getSummary(sessionId: string): Promise<CompressedSummary | null> {
    return this.summaryStore.get(sessionId);
  }

  /**
   * Compress conversation history if it exceeds threshold.
   */
  async maybeCompress(
    sessionId: string,
    messages: ModelMessage[],
  ): Promise<void> {
    // Count user-assistant rounds
    const rounds = messages.filter((m) => m.role === "user").length;
    if (rounds <= this.thresholdRounds) return;

    const existing = await this.summaryStore.get(sessionId);
    const startFrom = existing?.compressedThroughRound ?? 0;

    // Messages to compress (exclude last N rounds)
    const keepCount = this.keepLastRounds * 2; // user + assistant pairs
    const toCompress = messages.slice(0, Math.max(0, messages.length - keepCount));
    if (toCompress.length === 0) return;

    const conversationText = toCompress
      .map((m) => `${m.role}: ${typeof m.content === "string" ? m.content : JSON.stringify(m.content)}`)
      .join("\n");

    const previousSummary = existing?.summaryText ?? "";
    const prompt = previousSummary
      ? `Previous summary:\n${previousSummary}\n\nNew conversation to incorporate:\n${conversationText}\n\nCreate an updated comprehensive summary (max 500 words).`
      : `Summarize this conversation concisely (max 500 words), preserving key facts, decisions, and context:\n\n${conversationText}`;

    const result = await generateText({
      model: this.summaryModel,
      prompt,
      maxOutputTokens: 1000,
    });

    const summary: CompressedSummary = {
      summaryText: result.text,
      compressedThroughRound: startFrom + toCompress.filter((m) => m.role === "user").length,
      createdAt: Date.now(),
      modelUsed: "summary-model",
    };

    await this.summaryStore.save(sessionId, summary);
  }
}
