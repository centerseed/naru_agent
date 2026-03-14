"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.normalizeUsage = normalizeUsage;
/** Map Vercel AI SDK usage shape → naru TokenUsage. */
function normalizeUsage(usage) {
    const p = usage?.inputTokens ?? 0;
    const c = usage?.outputTokens ?? 0;
    return { promptTokens: p, completionTokens: c, totalTokens: usage?.totalTokens ?? p + c };
}
