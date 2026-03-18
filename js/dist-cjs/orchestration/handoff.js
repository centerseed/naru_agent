"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.AgentHandoffLoop = void 0;
/**
 * AgentHandoffLoop — follows handoff chains across agents with safety limits.
 */
class AgentHandoffLoop {
    agents;
    entry;
    maxHandoffs;
    name;
    constructor(agents, entry, maxHandoffs = 5, name = "handoff_loop") {
        this.agents = agents;
        this.entry = entry;
        this.maxHandoffs = maxHandoffs;
        this.name = name;
        if (agents.size === 0) {
            throw new Error("Handoff loop must have at least one agent");
        }
        if (!agents.has(entry)) {
            throw new Error(`Entry agent '${entry}' not found in agents`);
        }
    }
    async chat(message, options) {
        let currentAgent = this.entry;
        let currentMessage = message;
        let result = null;
        for (let i = 0; i <= this.maxHandoffs; i++) {
            const agent = this.agents.get(currentAgent);
            if (!agent) {
                throw new Error(`Unknown agent: ${currentAgent}`);
            }
            result = await agent.chat(currentMessage, options);
            if (!result.handoff) {
                return result;
            }
            currentAgent = result.handoff.target;
            currentMessage = result.handoff.message ?? message;
        }
        // Limit reached — return last result
        return result;
    }
}
exports.AgentHandoffLoop = AgentHandoffLoop;
