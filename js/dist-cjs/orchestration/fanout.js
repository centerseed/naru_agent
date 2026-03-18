"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.AgentFanout = void 0;
/**
 * AgentFanout — send the same message to multiple agents in parallel,
 * then merge results.
 */
class AgentFanout {
    agents;
    mergeFn;
    constructor(agents, options) {
        this.agents = agents;
        if (agents.length === 0) {
            throw new Error("Fan-out must have at least one agent");
        }
        this.mergeFn = options?.merge ?? AgentFanout.defaultMerge;
        this.name = options?.name ?? "fanout";
    }
    name;
    async chat(message, options) {
        const results = await Promise.all(this.agents.map((a) => a.chat(message, options)));
        return this.mergeFn(results);
    }
    static defaultMerge(results) {
        return {
            ...results[0],
            content: results
                .map((r) => r.content)
                .filter(Boolean)
                .join("\n\n---\n\n"),
        };
    }
}
exports.AgentFanout = AgentFanout;
