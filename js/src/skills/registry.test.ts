import { describe, it, expect } from "vitest";
import { skill, makeSkillResult } from "./base.js";
import { SkillRegistry } from "./registry.js";
import { KeywordSkillSelector } from "./selectors.js";

describe("SkillRegistry", () => {
  const greetingSkill = skill({
    name: "greeting",
    triggers: ["hello", "hi"],
    run: async (msg) =>
      makeSkillResult({
        promptInjection: `User said greeting: ${msg}`,
        skillName: "greeting",
      }),
  });

  const weatherSkill = skill({
    name: "weather",
    triggers: ["weather", "forecast"],
    run: async () =>
      makeSkillResult({
        promptInjection: "Check weather API",
        skillName: "weather",
      }),
  });

  it("selects skills by keyword", async () => {
    const registry = new SkillRegistry([greetingSkill, weatherSkill]);
    const selected = await registry.selectSkills("hello there");
    expect(selected).toHaveLength(1);
    expect(selected[0].name).toBe("greeting");
  });

  it("runs selected skills and returns results", async () => {
    const registry = new SkillRegistry([greetingSkill, weatherSkill]);
    const results = await registry.runSkills("hello", {
      message: "hello",
      memoryContext: "",
    });
    expect(results).toHaveLength(1);
    expect(results[0].promptInjection).toContain("greeting");
  });

  it("respects maxActiveSkills", async () => {
    const alwaysSkill = skill({
      name: "always",
      alwaysActive: true,
      triggers: [],
      run: async () => makeSkillResult({ skillName: "always" }),
    });
    const registry = new SkillRegistry(
      [alwaysSkill, greetingSkill, weatherSkill],
      new KeywordSkillSelector(),
      1,
    );
    const selected = await registry.selectSkills("hello weather");
    expect(selected.length).toBeLessThanOrEqual(1);
  });
});
