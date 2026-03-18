import type { NaruResult, ChatOptions } from "../types.js";
import type { AgentChatDelegate } from "./orchestrator.js";

/**
 * AgentPipeline — sequential pipeline where each stage's output
 * becomes the next stage's input.
 */
export class AgentPipeline implements AgentChatDelegate {
  constructor(
    private stages: AgentChatDelegate[],
    public readonly name: string = "pipeline",
  ) {
    if (stages.length === 0) {
      throw new Error("Pipeline must have at least one stage");
    }
  }

  async chat(message: string, options?: ChatOptions): Promise<NaruResult> {
    let currentMessage = message;
    let result: NaruResult | null = null;
    for (const stage of this.stages) {
      result = await stage.chat(currentMessage, options);
      currentMessage = result.content;
    }
    return result!;
  }
}
