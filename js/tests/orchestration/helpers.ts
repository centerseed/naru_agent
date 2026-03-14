import type { NaruResult } from "../../src/types.js";

/**
 * Shared test helper — creates a minimal valid NaruResult for use in orchestration tests.
 * Pass overrides to customize specific fields.
 */
export function makeMockNaruResult(overrides: Partial<NaruResult> = {}): NaruResult {
  return {
    content: "response",
    blocked: false,
    usage: { promptTokens: 0, completionTokens: 0, totalTokens: 0 },
    intent: null,
    toolCalls: [],
    timings: {},
    sessionId: null,
    traceId: null,
    trace: null,
    ...overrides,
  };
}
