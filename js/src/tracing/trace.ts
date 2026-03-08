export interface Span {
  spanId: string;
  traceId: string;
  name: string;
  startTime: number;
  endTime: number | null;
  attributes: Record<string, unknown>;
  status: "OK" | "ERROR";
  errorMessage: string | null;
}

export interface Trace {
  traceId: string;
  threadId: string | null;
  userId: string | null;
  startTime: number;
  endTime: number | null;
  input: string;
  output: string;
  blocked: boolean;
  usage: Record<string, number>;
  intent: Record<string, unknown> | null;
  toolCalls: string[];
  spans: Span[];
  metadata: Record<string, unknown>;
}

export function createTrace(partial: Partial<Trace> & { traceId: string }): Trace {
  return {
    threadId: null,
    userId: null,
    startTime: Date.now(),
    endTime: null,
    input: "",
    output: "",
    blocked: false,
    usage: {},
    intent: null,
    toolCalls: [],
    spans: [],
    metadata: {},
    ...partial,
  };
}

export function createSpan(
  partial: Partial<Span> & { spanId: string; traceId: string; name: string },
): Span {
  return {
    startTime: Date.now(),
    endTime: null,
    attributes: {},
    status: "OK",
    errorMessage: null,
    ...partial,
  };
}
