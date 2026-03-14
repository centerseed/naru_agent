import { describe, it, expect } from "vitest";
import { z } from "zod";
import { NaruAgent } from "../agent.js";
import { tool } from "../tools/base.js";
import { KeywordGuardrail } from "../guardrails/keyword.js";
import type { LanguageModel } from "ai";
import type {
  StructuredClassifier,
  StructuredClassifierInput,
  StructuredClassifierOutput,
} from "./types.js";
import { DecisionError } from "./types.js";

// ── Helpers ──────────────────────────────────────────────────────────

function createMockModel(response = "Hello!"): LanguageModel {
  return {
    specificationVersion: "v2",
    provider: "test",
    modelId: "test-model",
    supportedUrls: {},
    doGenerate: async () => ({
      content: [{ type: "text" as const, text: response }],
      finishReason: "stop" as const,
      usage: { inputTokens: 10, outputTokens: 5, totalTokens: 15 },
      warnings: [],
      response: {
        id: "test",
        timestamp: new Date(),
        modelId: "test-model",
      },
    }),
    doStream: async () => ({
      stream: new ReadableStream(),
      warnings: [],
    }),
  } as unknown as LanguageModel;
}

const TestSchema = z.object({
  intent: z.enum(["query", "mutate", "clarify"]),
  confidence: z.number(),
});
type TestDecision = z.infer<typeof TestSchema>;

function createMockClassifier(
  result: TestDecision,
  opts?: { name?: string; throwError?: Error },
): StructuredClassifier<TestDecision> {
  return {
    name: opts?.name ?? "TestClassifier",
    classify: async (
      input: StructuredClassifierInput,
    ): Promise<StructuredClassifierOutput<TestDecision>> => {
      if (opts?.throwError) throw opts.throwError;
      return {
        result,
        rawText: JSON.stringify(result),
        usage: { promptTokens: 8, completionTokens: 4, totalTokens: 12 },
        trace: { receivedInput: input },
      };
    },
  };
}

// ── Tests ────────────────────────────────────────────────────────────

describe("NaruAgent.decide()", () => {
  it("returns typed decision with rawText, usage, and timings", async () => {
    const agent = new NaruAgent({ model: createMockModel() });
    const classifier = createMockClassifier({
      intent: "query",
      confidence: 0.95,
    });

    const result = await agent.decide("What tasks are due?", classifier);

    expect(result.decision).toEqual({
      intent: "query",
      confidence: 0.95,
    });
    expect(result.rawText).toBe(
      JSON.stringify({ intent: "query", confidence: 0.95 }),
    );
    expect(result.usage.promptTokens).toBe(8);
    expect(result.usage.completionTokens).toBe(4);
    expect(result.timings.prefetch).toBeGreaterThanOrEqual(0);
    expect(result.timings.classify).toBeGreaterThanOrEqual(0);
    expect(result.timings.total).toBeGreaterThanOrEqual(0);
    expect(result.sessionId).toBeTruthy();
  });

  it("passes memory/summary/knowledge context to classifier", async () => {
    let capturedInput: StructuredClassifierInput | null = null;

    const classifier: StructuredClassifier<TestDecision> = {
      name: "ContextCapture",
      classify: async (input) => {
        capturedInput = input;
        return {
          result: { intent: "query", confidence: 0.8 },
          rawText: "{}",
        };
      },
    };

    // Use prefetchHooks to inject extra context (simulating memory/knowledge)
    const agent = new NaruAgent({
      model: createMockModel(),
      instructions: ["You are helpful."],
      prefetchHooks: [
        async () => "Hooked context data",
      ],
    });

    await agent.decide("test message", classifier, {
      userId: "u1",
      sessionId: "s1",
    });

    expect(capturedInput).not.toBeNull();
    expect(capturedInput!.message).toBe("test message");
    expect(capturedInput!.userId).toBe("u1");
    expect(capturedInput!.sessionId).toBe("s1");
    // extraContext should include instructions + hooked context
    expect(capturedInput!.extraContext).toBeDefined();
    expect(capturedInput!.extraContext!.some((c) => c.includes("You are helpful."))).toBe(true);
    expect(capturedInput!.extraContext!.some((c) => c.includes("Hooked context data"))).toBe(true);
  });

  it("throws DecisionError when input guardrail blocks", async () => {
    const agent = new NaruAgent({
      model: createMockModel(),
      guardrails: [
        new KeywordGuardrail({
          blockedPatterns: ["forbidden"],
          inputMessage: "Not allowed.",
        }),
      ],
    });

    const classifier = createMockClassifier({
      intent: "query",
      confidence: 1,
    });

    await expect(
      agent.decide("This is forbidden", classifier),
    ).rejects.toThrow(DecisionError);

    await expect(
      agent.decide("This is forbidden", classifier),
    ).rejects.toThrow("Not allowed.");
  });

  it("throws DecisionError with cause when classifier fails", async () => {
    const agent = new NaruAgent({ model: createMockModel() });
    const originalError = new Error("LLM API down");
    const classifier = createMockClassifier(
      { intent: "query", confidence: 0 },
      { throwError: originalError },
    );

    try {
      await agent.decide("test", classifier);
      expect.fail("Should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(DecisionError);
      expect((err as DecisionError).message).toBe("Classifier failed");
      expect((err as DecisionError).cause).toBe(originalError);
    }
  });

  it("includes trace with classifier name and context flags", async () => {
    const agent = new NaruAgent({
      model: createMockModel(),
      instructions: ["Be concise."],
    });

    const classifier = createMockClassifier(
      { intent: "mutate", confidence: 0.7 },
      { name: "MyCustomClassifier" },
    );

    const result = await agent.decide("Update my task", classifier);

    expect(result.trace).toBeDefined();
    expect(result.trace!.classifier).toBe("MyCustomClassifier");
    expect(result.trace!.usedSummary).toBe(false);
    expect(result.trace!.usedMemory).toBe(false);
    expect(result.trace!.usedKnowledge).toBe(false);
    expect(result.trace!.classifierTrace).toBeDefined();
  });

  it("does not affect existing chat() method", async () => {
    const agent = new NaruAgent({
      model: createMockModel("Chat response"),
    });

    const chatResult = await agent.chat("Hello");
    expect(chatResult.content).toBe("Chat response");
    expect(chatResult.blocked).toBe(false);

    const classifier = createMockClassifier({
      intent: "clarify",
      confidence: 0.6,
    });
    const decideResult = await agent.decide("Hello", classifier);
    expect(decideResult.decision.intent).toBe("clarify");

    // chat still works after decide
    const chatResult2 = await agent.chat("Hello again");
    expect(chatResult2.content).toBe("Chat response");
  });

  it("includes tool plan when includeToolPlan is true", async () => {
    // Create a model that produces tool calls
    const toolCallModel: LanguageModel = {
      specificationVersion: "v2",
      provider: "test",
      modelId: "test-model",
      supportedUrls: {},
      doGenerate: async () => ({
        content: [
          {
            type: "tool-call" as const,
            toolCallId: "tc1",
            toolName: "create_task",
            args: { title: "Buy groceries" },
          },
        ],
        finishReason: "tool-calls" as const,
        usage: { inputTokens: 15, outputTokens: 10, totalTokens: 25 },
        warnings: [],
        response: {
          id: "test",
          timestamp: new Date(),
          modelId: "test-model",
        },
      }),
      doStream: async () => ({
        stream: new ReadableStream(),
        warnings: [],
      }),
    } as unknown as LanguageModel;

    const testTool = tool({
      name: "create_task",
      description: "Create a new task",
      parameters: z.object({ title: z.string() }),
      execute: async () => {
        throw new Error("Should not be called in tool planning!");
      },
    });

    const agent = new NaruAgent({
      model: toolCallModel,
      tools: [testTool],
    });

    const classifier = createMockClassifier({
      intent: "mutate",
      confidence: 0.9,
    });

    const result = await agent.decide("Create a task: buy groceries", classifier, {
      includeToolPlan: true,
    });

    expect(result.decision.intent).toBe("mutate");
    expect(result.trace).toBeDefined();
    expect(result.trace!.toolPlan).toBeDefined();
    expect(result.trace!.toolPlan!.length).toBeGreaterThan(0);
    expect(result.trace!.toolPlan![0].tool).toBe("create_task");
    expect(result.timings.toolPlan).toBeGreaterThanOrEqual(0);
  });

  it("skips tool plan gracefully when no tools configured", async () => {
    const agent = new NaruAgent({ model: createMockModel() });
    const classifier = createMockClassifier({
      intent: "query",
      confidence: 0.5,
    });

    const result = await agent.decide("test", classifier, {
      includeToolPlan: true,
    });

    expect(result.trace!.toolPlan).toBeUndefined();
  });
});
