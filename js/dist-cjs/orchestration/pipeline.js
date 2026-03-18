"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.AgentPipeline = void 0;
/**
 * AgentPipeline — sequential pipeline where each stage's output
 * becomes the next stage's input.
 */
class AgentPipeline {
    stages;
    name;
    constructor(stages, name = "pipeline") {
        this.stages = stages;
        this.name = name;
        if (stages.length === 0) {
            throw new Error("Pipeline must have at least one stage");
        }
    }
    async chat(message, options) {
        let currentMessage = message;
        let result = null;
        for (const stage of this.stages) {
            result = await stage.chat(currentMessage, options);
            currentMessage = result.content;
        }
        return result;
    }
}
exports.AgentPipeline = AgentPipeline;
