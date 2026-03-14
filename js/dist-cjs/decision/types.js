"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.DecisionError = void 0;
// ── DecisionError ───────────────────────────────────────────────────
class DecisionError extends Error {
    cause;
    rawText;
    constructor(message, cause, rawText) {
        super(message);
        this.cause = cause;
        this.rawText = rawText;
        this.name = "DecisionError";
    }
}
exports.DecisionError = DecisionError;
