"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.TraceCollector = void 0;
const uuid_1 = require("uuid");
const trace_js_1 = require("./trace.js");
class TraceCollector {
    eventBus;
    currentTrace = null;
    activeSpans = new Map();
    constructor(eventBus) {
        this.eventBus = eventBus;
        this.setupListeners();
    }
    setupListeners() {
        this.eventBus.on("memory_retrieved", (data) => {
            this.addSpanEvent("memory_retrieval", data);
        });
        this.eventBus.on("intent_classified", (data) => {
            this.addSpanEvent("intent_classification", data);
        });
        this.eventBus.on("knowledge_retrieved", (data) => {
            this.addSpanEvent("knowledge_retrieval", data);
        });
        this.eventBus.on("before_llm_call", () => {
            this.startSpan("llm_call");
        });
        this.eventBus.on("after_llm_call", () => {
            this.endSpan("llm_call");
        });
    }
    startTrace(message, userId, sessionId) {
        const traceId = (0, uuid_1.v4)();
        this.currentTrace = (0, trace_js_1.createTrace)({
            traceId,
            threadId: sessionId ?? null,
            userId: userId ?? null,
            input: message,
        });
        return traceId;
    }
    startSpan(name, attributes) {
        if (!this.currentTrace)
            return "";
        const spanId = (0, uuid_1.v4)();
        const span = (0, trace_js_1.createSpan)({
            spanId,
            traceId: this.currentTrace.traceId,
            name,
            attributes,
        });
        this.activeSpans.set(name, span);
        return spanId;
    }
    endSpan(name, error) {
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
    addSpanEvent(name, data) {
        if (!this.currentTrace)
            return;
        const span = (0, trace_js_1.createSpan)({
            spanId: (0, uuid_1.v4)(),
            traceId: this.currentTrace.traceId,
            name,
            endTime: Date.now(),
            attributes: data ?? {},
        });
        this.currentTrace.spans.push(span);
    }
    endTrace(result) {
        if (!this.currentTrace)
            return null;
        this.currentTrace.endTime = Date.now();
        this.currentTrace.output = result.content;
        this.currentTrace.blocked = result.blocked;
        this.currentTrace.usage = result.usage;
        this.currentTrace.toolCalls = result.toolCalls;
        if (result.intent) {
            this.currentTrace.intent = result.intent;
        }
        const trace = this.currentTrace;
        this.currentTrace = null;
        this.activeSpans.clear();
        return trace;
    }
}
exports.TraceCollector = TraceCollector;
