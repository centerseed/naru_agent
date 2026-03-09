"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.JSONLTraceExporter = void 0;
const promises_1 = require("node:fs/promises");
/**
 * Exports traces as JSONL (one JSON object per line).
 */
class JSONLTraceExporter {
    filePath;
    constructor(filePath) {
        this.filePath = filePath;
    }
    async export(trace) {
        await (0, promises_1.appendFile)(this.filePath, JSON.stringify(trace) + "\n", "utf-8");
    }
}
exports.JSONLTraceExporter = JSONLTraceExporter;
