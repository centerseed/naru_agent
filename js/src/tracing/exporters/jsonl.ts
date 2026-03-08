import { appendFile } from "node:fs/promises";
import type { Trace } from "../trace.js";

export interface BaseTraceExporter {
  export(trace: Trace): Promise<void>;
}

/**
 * Exports traces as JSONL (one JSON object per line).
 */
export class JSONLTraceExporter implements BaseTraceExporter {
  private filePath: string;

  constructor(filePath: string) {
    this.filePath = filePath;
  }

  async export(trace: Trace): Promise<void> {
    await appendFile(this.filePath, JSON.stringify(trace) + "\n", "utf-8");
  }
}
