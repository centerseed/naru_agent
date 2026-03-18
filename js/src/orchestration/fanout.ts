import type { NaruResult, ChatOptions } from "../types.js";
import type { AgentChatDelegate } from "./orchestrator.js";

/**
 * AgentFanout — send the same message to multiple agents in parallel,
 * then merge results.
 */
export class AgentFanout implements AgentChatDelegate {
  private mergeFn: (results: NaruResult[]) => NaruResult;

  constructor(
    private agents: AgentChatDelegate[],
    options?: {
      merge?: (results: NaruResult[]) => NaruResult;
      name?: string;
    },
  ) {
    if (agents.length === 0) {
      throw new Error("Fan-out must have at least one agent");
    }
    this.mergeFn = options?.merge ?? AgentFanout.defaultMerge;
    this.name = options?.name ?? "fanout";
  }

  public readonly name: string;

  async chat(message: string, options?: ChatOptions): Promise<NaruResult> {
    const results = await Promise.all(
      this.agents.map((a) => a.chat(message, options)),
    );
    return this.mergeFn(results);
  }

  private static defaultMerge(results: NaruResult[]): NaruResult {
    return {
      ...results[0],
      content: results
        .map((r) => r.content)
        .filter(Boolean)
        .join("\n\n---\n\n"),
    };
  }
}
