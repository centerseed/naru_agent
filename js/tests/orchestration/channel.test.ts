import { describe, it, expect, vi } from "vitest";
import { AgentOrchestrator } from "../../src/orchestration/orchestrator.js";
import type { ChannelAdapter, ChannelMessage } from "../../src/orchestration/channel.js";
import type { OrchestrationResult } from "../../src/orchestration/result.js";
import { makeMockNaruResult } from "./helpers.js";

interface LineMessage {
  events: Array<{ message: { text: string }; source: { userId: string } }>;
}

interface LineReply {
  replyText: string;
  userId: string;
}

describe("ChannelAdapter - AC8", () => {
  it("should transform incoming channel message and outgoing result", async () => {
    const adapter: ChannelAdapter<LineMessage, LineReply> = {
      parseIncoming: (input: LineMessage): ChannelMessage => ({
        text: input.events[0].message.text,
        options: { userId: input.events[0].source.userId },
      }),
      formatOutgoing: (result: OrchestrationResult): LineReply => ({
        replyText: result.content,
        userId: result.sessionId ?? "unknown",
      }),
    };

    const orchestrator = new AgentOrchestrator({
      delegate: { chat: async () => makeMockNaruResult({ content: "Hello from agent" }) },
      channelAdapter: adapter as ChannelAdapter,
    });

    const rawInput: LineMessage = {
      events: [
        { message: { text: "Hi there" }, source: { userId: "user-123" } },
      ],
    };

    const output = await orchestrator.processChannel<LineMessage, LineReply>(rawInput);

    expect(output.replyText).toBe("Hello from agent");
    expect(output.userId).toBeDefined();
  });

  it("should call parseIncoming then chat then formatOutgoing in sequence", async () => {
    const callOrder: string[] = [];

    const adapter: ChannelAdapter<string, string> = {
      parseIncoming: (input: string): ChannelMessage => {
        callOrder.push("parseIncoming");
        return { text: input };
      },
      formatOutgoing: (result: OrchestrationResult): string => {
        callOrder.push("formatOutgoing");
        return result.content.toUpperCase();
      },
    };

    const orchestrator = new AgentOrchestrator({
      delegate: {
        chat: async () => {
          callOrder.push("chat");
          return makeMockNaruResult({ content: "response" });
        },
      },
      channelAdapter: adapter as ChannelAdapter,
    });

    const output = await orchestrator.processChannel<string, string>("hello");

    expect(callOrder).toEqual(["parseIncoming", "chat", "formatOutgoing"]);
    expect(output).toBe("RESPONSE");
  });

  it("should throw error when processChannel called without channelAdapter", async () => {
    const orchestrator = new AgentOrchestrator({
      delegate: { chat: async () => makeMockNaruResult({ content: "response" }) },
    });

    await expect(orchestrator.processChannel("raw input")).rejects.toThrow("No channelAdapter configured");
  });

  it("should pass parsed options to chat", async () => {
    let receivedOptions: unknown;
    const adapter: ChannelAdapter<string, string> = {
      parseIncoming: (): ChannelMessage => ({
        text: "parsed message",
        options: { userId: "parsed-user", sessionId: "parsed-session" },
      }),
      formatOutgoing: (result: OrchestrationResult): string => result.content,
    };

    const orchestrator = new AgentOrchestrator({
      delegate: {
        chat: async (_msg, opts) => {
          receivedOptions = opts;
          return makeMockNaruResult({ content: "ok" });
        },
      },
      channelAdapter: adapter as ChannelAdapter,
    });

    await orchestrator.processChannel("raw");
    expect((receivedOptions as Record<string, string>)?.userId).toBe("parsed-user");
    expect((receivedOptions as Record<string, string>)?.sessionId).toBe("parsed-session");
  });
});
