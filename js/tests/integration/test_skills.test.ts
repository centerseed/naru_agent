/**
 * Skills Integration Tests — @ac8, @ac9, @ac10
 *
 * Covers:
 *   @ac8 — 關鍵字觸發 + 無觸發詞不啟動 Skill
 *   @ac9 — Skill 注入額外工具
 *   @ac10 — Always-active Skill
 *
 * Execute:
 *   GOOGLE_GENERATIVE_AI_API_KEY=xxx npx vitest run tests/integration/test_skills.test.ts
 */

import { describe, it, expect, beforeEach } from "vitest";
import { z } from "zod";
import {
  callLog,
  clearCallLog,
  makeAgent,
} from "./helpers.js";
import { loadScenarios } from "./scenario-runner.js";
import { skill, makeSkillResult, tool } from "../../src/index.js";

const HAS_API_KEY = !!process.env.GOOGLE_GENERATIVE_AI_API_KEY;
const describeIf = HAS_API_KEY ? describe : describe.skip;

const scenarios = loadScenarios("skills.json");

// ---------------------------------------------------------------------------
// Build skills from scenario definitions
// ---------------------------------------------------------------------------

interface SkillDef {
  name: string;
  description: string;
  triggers: string[];
  alwaysActive?: boolean;
  promptInjection: string;
  extraTools?: Array<{
    name: string;
    description: string;
    parameters: Record<string, string>;
    mockReturn: string;
  }>;
}

const skillsDefs = scenarios.skills_definition as Record<string, SkillDef>;

function buildWeatherSkill() {
  const def = skillsDefs["weather_skill"]!;
  const weatherTool = tool({
    name: "get_weather",
    description: "查詢指定城市天氣",
    parameters: z.object({ city: z.string() }),
    execute: async ({ city }) => {
      callLog.push({ tool: "get_weather", city });
      return JSON.stringify({ city, temp: "22°C", condition: "晴天" });
    },
  });

  return skill({
    name: def.name,
    description: def.description,
    triggers: def.triggers,
    alwaysActive: def.alwaysActive ?? false,
    run: async (message, _context) => {
      const triggered = def.triggers.some((t) => message.includes(t));
      if (!triggered) {
        return makeSkillResult({ skillName: def.name, skipped: true });
      }
      return makeSkillResult({
        skillName: def.name,
        promptInjection: def.promptInjection,
        extraTools: [weatherTool],
      });
    },
  });
}

function buildGreetingSkill() {
  const def = skillsDefs["greeting_skill"]!;
  return skill({
    name: def.name,
    description: def.description,
    triggers: def.triggers,
    alwaysActive: def.alwaysActive ?? false,
    run: async (_message, _context) => {
      return makeSkillResult({
        skillName: def.name,
        promptInjection: def.promptInjection,
      });
    },
  });
}

// ---------------------------------------------------------------------------
// @ac8 — 關鍵字觸發 Skill
// ---------------------------------------------------------------------------

describeIf("Skills_KeywordTrigger (@ac8)", () => {
  beforeEach(() => clearCallLog());

  it("keyword trigger activates weather skill", async () => {
    const s = scenarios.scenarios.find((s) => s.id === "keyword_trigger")!;
    const weatherSkill = buildWeatherSkill();
    const agent = makeAgent({ tools: [], skills: [weatherSkill] });

    const result = await agent.chat(s.input!);

    expect(result.blocked).toBe(false);
    expect(result.toolCalls).toContain("get_weather");
  }, 60_000);

  it("no trigger word does not activate weather skill", async () => {
    const s = scenarios.scenarios.find((s) => s.id === "no_trigger")!;
    const weatherSkill = buildWeatherSkill();
    const agent = makeAgent({ tools: [], skills: [weatherSkill] });

    const result = await agent.chat(s.input!);

    expect(result.toolCalls).not.toContain("get_weather");
  }, 60_000);
});

// ---------------------------------------------------------------------------
// @ac9 — Skill 注入額外工具
// ---------------------------------------------------------------------------

describeIf("Skills_ToolInjection (@ac9)", () => {
  beforeEach(() => clearCallLog());

  it("skill injects get_weather tool and it is used", async () => {
    const s = scenarios.scenarios.find((s) => s.id === "skill_injects_tool")!;
    const weatherSkill = buildWeatherSkill();
    const agent = makeAgent({ tools: [], skills: [weatherSkill] });

    const result = await agent.chat(s.input!);

    expect(result.toolCalls).toContain("get_weather");
    expect(
      result.content.includes("高雄"),
    ).toBe(true);
  }, 60_000);
});

// ---------------------------------------------------------------------------
// @ac10 — Always-active Skill
// ---------------------------------------------------------------------------

describeIf("Skills_AlwaysActive (@ac10)", () => {
  it("always-active greeting skill responds to any input", async () => {
    const s = scenarios.scenarios.find((s) => s.id === "always_active")!;
    const greetingSkill = buildGreetingSkill();
    const agent = makeAgent({ tools: [], skills: [greetingSkill] });

    const result = await agent.chat(s.input!);

    expect(result.blocked).toBe(false);
    expect(result.content.length).toBeGreaterThan(0);
    // Verify the prompt injection ("每次回覆開頭加上友善的問候語") visibly affected the response.
    // A regression where alwaysActive is silently ignored would omit greeting language.
    const hasGreeting = /你好|您好|歡迎|嗨|Hi|Hello|Greet/i.test(result.content);
    expect(hasGreeting).toBe(true);
  }, 60_000);
});
