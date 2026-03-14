import type { ChatOptions } from "../types.js";
import type { OrchestrationResult } from "./result.js";

/**
 * ChannelMessage — normalized input from any channel.
 */
export interface ChannelMessage {
  text: string;
  options?: ChatOptions;
  raw?: unknown;
}

/**
 * ChannelAdapter<TIn, TOut> — abstracts channel-specific I/O transformation.
 */
export interface ChannelAdapter<TIn = unknown, TOut = unknown> {
  parseIncoming(input: TIn): ChannelMessage;
  formatOutgoing(result: OrchestrationResult): TOut;
}
