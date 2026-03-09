"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.createTrace = createTrace;
exports.createSpan = createSpan;
function createTrace(partial) {
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
function createSpan(partial) {
    return {
        startTime: Date.now(),
        endTime: null,
        attributes: {},
        status: "OK",
        errorMessage: null,
        ...partial,
    };
}
