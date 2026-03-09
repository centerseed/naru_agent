"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.skill = skill;
exports.makeSkillResult = makeSkillResult;
/**
 * Factory function to create a skill (equivalent to Python @skill decorator).
 */
function skill(config) {
    return {
        name: config.name,
        description: config.description ?? "",
        triggers: config.triggers ?? [],
        priority: config.priority ?? 0,
        alwaysActive: config.alwaysActive ?? false,
        run: config.run,
    };
}
function makeSkillResult(partial) {
    return {
        promptInjection: "",
        extraTools: [],
        overrideSystemPrompt: null,
        skillName: "",
        skipped: false,
        ...partial,
    };
}
