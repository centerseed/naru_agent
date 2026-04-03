import { describe, it, expect, vi } from "vitest";
import { skill } from "../../../src/skills/base.js";
import { LLMSkillSelector } from "../../../src/skills/selectors.js";
import type { SkillContext } from "../../../src/skills/base.js";

// ── Helpers ──

function makeContext(): SkillContext {
  return { message: "", memoryContext: "" };
}

function makeCalendarSkill() {
  return skill({
    name: "calendar",
    description: "Query calendar events",
    triggers: ["calendar", "行事曆"],
    triggerConditions: ["用戶想查詢行事曆、問某天有什麼行程"],
    exclusionConditions: ["用戶只是提到日期但意圖是記錄或交辦，不是查行事曆"],
    run: async () => ({ promptInjection: "calendar context", extraTools: [], overrideSystemPrompt: null, skillName: "calendar", skipped: false }),
  });
}

function makeReminderSkill() {
  return skill({
    name: "reminder",
    description: "Set reminders",
    triggers: ["remind", "reminder"],
    run: async () => ({ promptInjection: "reminder context", extraTools: [], overrideSystemPrompt: null, skillName: "reminder", skipped: false }),
  });
}

function makeAlwaysActiveSkill() {
  return skill({
    name: "always",
    description: "Always on",
    alwaysActive: true,
    run: async () => ({ promptInjection: "always context", extraTools: [], overrideSystemPrompt: null, skillName: "always", skipped: false }),
  });
}

// ── Tests ──

describe("LLMSkillSelector", () => {
  it("test_llm_selector_matches_trigger_conditions", async () => {
    const calendar = makeCalendarSkill();
    const reminder = makeReminderSkill();
    const chatFn = vi.fn().mockResolvedValue('["calendar"]');

    const selector = new LLMSkillSelector(chatFn);
    const result = await selector.select([calendar, reminder], "星期三有什麼行程？");

    expect(result).toHaveLength(1);
    expect(result[0].name).toBe("calendar");
    expect(chatFn).toHaveBeenCalledOnce();
  });

  it("test_llm_selector_excludes_by_exclusion_conditions", async () => {
    const calendar = makeCalendarSkill();
    const chatFn = vi.fn().mockResolvedValue("[]");

    const selector = new LLMSkillSelector(chatFn);
    const result = await selector.select([calendar], "星期三要開會（記錄一下）");

    expect(result).toHaveLength(0);
    expect(chatFn).toHaveBeenCalledOnce();
  });

  it("test_llm_selector_always_active_included", async () => {
    const calendar = makeCalendarSkill();
    const always = makeAlwaysActiveSkill();
    const chatFn = vi.fn().mockResolvedValue('["calendar"]');

    const selector = new LLMSkillSelector(chatFn);
    const result = await selector.select([calendar, always], "查行事曆");

    const names = new Set(result.map((s) => s.name));
    expect(names).toContain("always");
    expect(names).toContain("calendar");
    // always_active skill must NOT appear in the prompt
    const promptArg = chatFn.mock.calls[0][0] as string;
    expect(promptArg).not.toContain("always");
  });

  it("test_llm_selector_empty_candidates", async () => {
    const always = makeAlwaysActiveSkill();
    const chatFn = vi.fn();

    const selector = new LLMSkillSelector(chatFn);
    const result = await selector.select([always], "any message");

    expect(result).toHaveLength(1);
    expect(result[0].name).toBe("always");
    expect(chatFn).not.toHaveBeenCalled();
  });

  it("test_llm_selector_fallback_to_triggers", async () => {
    const reminder = makeReminderSkill(); // no triggerConditions
    const chatFn = vi.fn().mockResolvedValue("[]");

    const selector = new LLMSkillSelector(chatFn);
    await selector.select([reminder], "set a reminder");

    const prompt = chatFn.mock.calls[0][0] as string;
    expect(prompt).toContain("remind"); // triggers visible as fallback
  });

  it("test_llm_selector_parse_response_json", async () => {
    const calendar = makeCalendarSkill();
    const reminder = makeReminderSkill();
    const chatFn = vi.fn().mockResolvedValue('["calendar", "reminder"]');

    const selector = new LLMSkillSelector(chatFn);
    const result = await selector.select([calendar, reminder], "查行事曆並設提醒");

    const names = new Set(result.map((s) => s.name));
    expect(names).toContain("calendar");
    expect(names).toContain("reminder");
  });

  it("test_llm_selector_parse_response_with_extra_text", async () => {
    const calendar = makeCalendarSkill();
    const chatFn = vi.fn().mockResolvedValue(
      'Sure! Based on the message, the skills to activate are: ["calendar"].'
    );

    const selector = new LLMSkillSelector(chatFn);
    const result = await selector.select([calendar], "查行事曆");

    expect(result).toHaveLength(1);
    expect(result[0].name).toBe("calendar");
  });

  it("test_llm_selector_builds_correct_prompt", async () => {
    const calendar = makeCalendarSkill();
    const chatFn = vi.fn().mockResolvedValue("[]");

    const selector = new LLMSkillSelector(chatFn);
    await selector.select([calendar], "test message");

    const prompt = chatFn.mock.calls[0][0] as string;
    expect(prompt).toContain("trigger_conditions");
    expect(prompt).toContain("exclusion_conditions");
    expect(prompt).toContain("用戶想查詢行事曆");
    expect(prompt).toContain("用戶只是提到日期");
    expect(prompt).toContain("test message");
  });
});
