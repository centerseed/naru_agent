import { describe, it, expect } from "vitest";
import { KeywordGuardrail } from "./keyword.js";

describe("KeywordGuardrail", () => {
  it("blocks input matching pattern", async () => {
    const guard = new KeywordGuardrail({
      blockedPatterns: ["hack", "exploit"],
    });
    const result = await guard.checkInput("how to hack a server");
    expect(result.passed).toBe(false);
  });

  it("passes clean input", async () => {
    const guard = new KeywordGuardrail({
      blockedPatterns: ["hack"],
    });
    const result = await guard.checkInput("how to bake a cake");
    expect(result.passed).toBe(true);
  });

  it("blocks output matching pattern", async () => {
    const guard = new KeywordGuardrail({
      blockedPatterns: ["secret"],
      outputReplacement: "[REDACTED]",
    });
    const result = await guard.checkOutput("The secret is 42");
    expect(result.passed).toBe(false);
    expect(result.modifiedText).toBe("[REDACTED]");
  });
});
