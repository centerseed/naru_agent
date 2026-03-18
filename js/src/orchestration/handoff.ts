import type { NaruResult, ChatOptions } from "../types.js";
import type { AgentChatDelegate } from "./orchestrator.js";

/**
 * AgentHandoffLoop — follows handoff chains across agents with safety limits.
 */
export class AgentHandoffLoop implements AgentChatDelegate {
  constructor(
    private agents: Map<string, AgentChatDelegate>,
    private entry: string,
    private maxHandoffs: number = 5,
    public readonly name: string = "handoff_loop",
  ) {
    if (agents.size === 0) {
      throw new Error("Handoff loop must have at least one agent");
    }
    if (!agents.has(entry)) {
      throw new Error(`Entry agent '${entry}' not found in agents`);
    }
  }

  async chat(message: string, options?: ChatOptions): Promise<NaruResult> {
    let currentAgent = this.entry;
    let currentMessage = message;
    let result: NaruResult | null = null;

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
    return result!;
  }
}
