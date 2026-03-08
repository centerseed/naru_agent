import { v4 as uuidv4 } from "uuid";
import type { EventBus } from "../event-bus.js";
import type { NaruResult } from "../types.js";
import { createTrace, createSpan, type Trace, type Span } from "./trace.js";

export class TraceCollector {
  private eventBus: EventBus;
  private currentTrace: Trace | null = null;
  private activeSpans = new Map<string, Span>();

  constructor(eventBus: EventBus) {
    this.eventBus = eventBus;
    this.setupListeners();
  }

  private setupListeners(): void {
    this.eventBus.on("memory_retrieved", (data) => {
      this.addSpanEvent("memory_retrieval", data as Record<string, unknown>);
    });
    this.eventBus.on("intent_classified", (data) => {
      this.addSpanEvent("intent_classification", data as Record<string, unknown>);
    });
    this.eventBus.on("knowledge_retrieved", (data) => {
      this.addSpanEvent("knowledge_retrieval", data as Record<string, unknown>);
    });
    this.eventBus.on("before_llm_call", () => {
      this.startSpan("llm_call");
    });
    this.eventBus.on("after_llm_call", () => {
      this.endSpan("llm_call");
    });
  }

  startTrace(
    message: string,
    userId?: string,
    sessionId?: string,
  ): string {
    const traceId = uuidv4();
    this.currentTrace = createTrace({
      traceId,
      threadId: sessionId ?? null,
      userId: userId ?? null,
      input: message,
    });
    return traceId;
  }

  startSpan(name: string, attributes?: Record<string, unknown>): string {
    if (!this.currentTrace) return "";
    const spanId = uuidv4();
    const span = createSpan({
      spanId,
      traceId: this.currentTrace.traceId,
      name,
      attributes,
    });
    this.activeSpans.set(name, span);
    return spanId;
  }

  endSpan(name: string, error?: string): void {
    const span = this.activeSpans.get(name);
    if (span) {
      span.endTime = Date.now();
      if (error) {
        span.status = "ERROR";
        span.errorMessage = error;
      }
      this.currentTrace?.spans.push(span);
      this.activeSpans.delete(name);
    }
  }

  private addSpanEvent(name: string, data?: Record<string, unknown>): void {
    if (!this.currentTrace) return;
    const span = createSpan({
      spanId: uuidv4(),
      traceId: this.currentTrace.traceId,
      name,
      endTime: Date.now(),
      attributes: data ?? {},
    });
    this.currentTrace.spans.push(span);
  }

  endTrace(result: NaruResult): Trace | null {
    if (!this.currentTrace) return null;
    this.currentTrace.endTime = Date.now();
    this.currentTrace.output = result.content;
    this.currentTrace.blocked = result.blocked;
    this.currentTrace.usage = result.usage as unknown as Record<string, number>;
    this.currentTrace.toolCalls = result.toolCalls;
    if (result.intent) {
      this.currentTrace.intent = result.intent as unknown as Record<string, unknown>;
    }
    const trace = this.currentTrace;
    this.currentTrace = null;
    this.activeSpans.clear();
    return trace;
  }
}
