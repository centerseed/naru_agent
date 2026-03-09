"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.SkillRegistry = void 0;
const selectors_js_1 = require("./selectors.js");
const base_js_1 = require("./base.js");
class SkillRegistry {
    skills;
    selector;
    maxActiveSkills;
    constructor(skills, selector, maxActiveSkills = 3) {
        this.skills = skills;
        this.selector = selector ?? new selectors_js_1.KeywordSkillSelector();
        this.maxActiveSkills = maxActiveSkills;
    }
    async selectSkills(message) {
        const selected = await this.selector.select(this.skills, message);
        return selected
            .sort((a, b) => b.priority - a.priority)
            .slice(0, this.maxActiveSkills);
    }
    async runSkills(message, context) {
        const selected = await this.selectSkills(message);
        if (selected.length === 0)
            return [];
        const results = await Promise.allSettled(selected.map(async (s) => {
            try {
                const result = await s.run(message, context);
                return { ...result, skillName: s.name };
            }
            catch {
                return (0, base_js_1.makeSkillResult)({ skillName: s.name, skipped: true });
            }
        }));
        return results
            .filter((r) => r.status === "fulfilled")
            .map((r) => r.value)
            .filter((r) => !r.skipped);
    }
}
exports.SkillRegistry = SkillRegistry;
