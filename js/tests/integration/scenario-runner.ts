/**
 * Shared scenario runner helpers for integration tests.
 *
 * Provides:
 *   - ScenarioExpect type matching the assertion DSL
 *   - assertScenarioResult() to validate NaruResult against scenario expectations
 *   - loadScenarios() to read JSON scenario files from tests/shared/
 */

import { expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import type { NaruResult } from "../../src/types.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

// ---------------------------------------------------------------------------
// Shared root — tests/shared/ is three levels up from js/tests/integration/
// ---------------------------------------------------------------------------

const SHARED_ROOT = resolve(__dirname, "../../../tests/shared");

// ---------------------------------------------------------------------------
// Type definitions for scenario format
// ---------------------------------------------------------------------------

export interface ScenarioExpect {
  blocked?: boolean;
  content_not_empty?: boolean;
  content_keywords_any?: string[];
  content_keywords_all?: string[];
  toolCalls_contains?: string[];
  toolCalls_contains_any?: string[];
  toolCalls_not_contains?: string[];
  toolCalls_max_count?: number;
  toolCalls_min_count?: number;
  /** Reference to a baseline key or a numeric token limit */
  tokens_max?: string | number;
  /** Minimum number of trace spans */
  trace_min_spans?: number;
  /** Streaming event types that must be present */
  has_stream_events?: string[];
}

export interface Scenario {
  id: string;
  ac: string;
  description: string;
  input?: string;
  skill?: string;
  tags?: string[];
  type?: string;
  expect: ScenarioExpect;
  [key: string]: unknown;
}

export interface ScenariosFile {
  scenarios: Scenario[];
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// assertScenarioResult
// ---------------------------------------------------------------------------

/**
 * Validate a NaruResult against a ScenarioExpect definition.
 * Pass the loaded baseline to resolve token budget references.
 */
export function assertScenarioResult(
  result: NaruResult,
  scenarioExpect: ScenarioExpect,
  baseline?: Record<string, number | boolean>,
): void {
  if (scenarioExpect.blocked !== undefined) {
    expect(result.blocked).toBe(scenarioExpect.blocked);
  }

  if (scenarioExpect.content_not_empty) {
    expect(result.content.length).toBeGreaterThan(0);
  }

  if (scenarioExpect.content_keywords_any) {
    const content = result.content.toLowerCase();
    const found = scenarioExpect.content_keywords_any.some((kw) =>
      content.includes(kw.toLowerCase()),
    );
    expect(found).toBe(true);
  }

  if (scenarioExpect.content_keywords_all) {
    const content = result.content.toLowerCase();
    for (const kw of scenarioExpect.content_keywords_all) {
      expect(content.includes(kw.toLowerCase())).toBe(true);
    }
  }

  if (scenarioExpect.toolCalls_contains) {
    for (const tool of scenarioExpect.toolCalls_contains) {
      expect(result.toolCalls).toContain(tool);
    }
  }

  if (scenarioExpect.toolCalls_contains_any) {
    const found = scenarioExpect.toolCalls_contains_any.some((tool) =>
      result.toolCalls.includes(tool),
    );
    expect(found).toBe(true);
  }

  if (scenarioExpect.toolCalls_not_contains) {
    for (const tool of scenarioExpect.toolCalls_not_contains) {
      expect(result.toolCalls).not.toContain(tool);
    }
  }

  if (scenarioExpect.toolCalls_max_count !== undefined) {
    expect(result.toolCalls.length).toBeLessThanOrEqual(
      scenarioExpect.toolCalls_max_count,
    );
  }

  if (scenarioExpect.toolCalls_min_count !== undefined) {
    expect(result.toolCalls.length).toBeGreaterThanOrEqual(
      scenarioExpect.toolCalls_min_count,
    );
  }

  if (scenarioExpect.trace_min_spans !== undefined) {
    // NOTE: trace_min_spans cannot be asserted on NaruResult alone.
    // NaruResult does not expose span data directly. Span assertions must be
    // performed inline in test_quality.test.ts using the JSONL trace file.
    // This field is intentionally not checked here to avoid silent no-op confusion.
    // To assert spans, read the trace file and check spans.length >= trace_min_spans.
    throw new Error(
      `trace_min_spans (${scenarioExpect.trace_min_spans}) cannot be asserted via assertScenarioResult. ` +
        "Use inline trace file assertions in test_quality.test.ts instead.",
    );
  }

  if (scenarioExpect.has_stream_events !== undefined) {
    // NOTE: has_stream_events cannot be asserted on NaruResult (non-streaming).
    // Streaming tests must collect events inline and assert them directly.
    // This field is intentionally not checked here to avoid silent no-op confusion.
    // To assert stream events, use the streaming API and check the event list.
    throw new Error(
      `has_stream_events cannot be asserted via assertScenarioResult on a NaruResult. ` +
        "Use inline streaming assertions in test_streaming.test.ts instead.",
    );
  }

  if (scenarioExpect.tokens_max !== undefined) {
    let maxTokens: number;
    if (typeof scenarioExpect.tokens_max === "string") {
      // Look up in baseline
      if (!baseline) {
        throw new Error(
          `tokens_max references baseline key "${scenarioExpect.tokens_max}" but no baseline was provided`,
        );
      }
      maxTokens = baseline[scenarioExpect.tokens_max] as number;
    } else {
      maxTokens = scenarioExpect.tokens_max;
    }
    expect(result.usage.totalTokens).toBeLessThanOrEqual(maxTokens);
  }
}

// ---------------------------------------------------------------------------
// loadScenarios
// ---------------------------------------------------------------------------

/**
 * Load a scenario JSON file from tests/shared/scenarios/.
 * @param fileName e.g. "tool-calling.json"
 */
export function loadScenarios(fileName: string): ScenariosFile {
  const filePath = resolve(SHARED_ROOT, "scenarios", fileName);
  const raw = readFileSync(filePath, "utf-8");
  return JSON.parse(raw) as ScenariosFile;
}

/**
 * Load knowledge data from tests/shared/knowledge/.
 * @param fileName e.g. "facts.json"
 */
export function loadKnowledge(fileName: string): unknown {
  const filePath = resolve(SHARED_ROOT, "knowledge", fileName);
  const raw = readFileSync(filePath, "utf-8");
  return JSON.parse(raw);
}

/**
 * Load the shared quality baseline from tests/shared/baselines/.
 */
export function loadSharedBaseline(): Record<string, number | boolean> {
  const filePath = resolve(SHARED_ROOT, "baselines/quality_baseline.json");
  const raw = readFileSync(filePath, "utf-8");
  return JSON.parse(raw);
}
