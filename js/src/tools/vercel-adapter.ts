import { tool as vercelTool, type ToolSet } from "ai";
import type { BaseTool } from "./base.js";

/** Simple counting semaphore to limit concurrent async operations. */
class Semaphore {
  private permits: number;
  private readonly queue: (() => void)[] = [];

  constructor(permits: number) {
    this.permits = permits;
  }

  acquire(): Promise<void> {
    if (this.permits > 0) {
      this.permits--;
      return Promise.resolve();
    }
    return new Promise((resolve) => this.queue.push(resolve));
  }

  release(): void {
    if (this.queue.length > 0) {
      this.queue.shift()!();
    } else {
      this.permits++;
    }
  }
}

export interface ToVercelToolsOptions {
  /** Max number of tool calls executed in parallel within a single LLM step. Default: unlimited. */
  maxParallelTools?: number;
}

/**
 * Convert naru BaseTool[] to Vercel AI SDK ToolSet record.
 *
 * @example
 * const tools = toVercelTools([weatherTool, searchTool]);
 * const result = await generateText({ model, tools, prompt: "..." });
 */
export function toVercelTools(
  tools: BaseTool[],
  options: ToVercelToolsOptions = {},
): ToolSet {
  const semaphore =
    options.maxParallelTools != null && options.maxParallelTools > 0
      ? new Semaphore(options.maxParallelTools)
      : null;

  const result: Record<string, unknown> = {};
  for (const t of tools) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    result[t.name] = (vercelTool as any)({
      description: t.description,
      parameters: t.parameters,
      execute: async (params: Record<string, unknown>) => {
        if (semaphore) await semaphore.acquire();
        try {
          const maxAttempts = (t.retries ?? 0) + 1;
          for (let attempt = 1; attempt <= maxAttempts; attempt++) {
            try {
              const exec = t.execute(params);
              if (t.timeout != null) {
                let timerId: ReturnType<typeof setTimeout>;
                const timeout = new Promise<never>((_, reject) => {
                  timerId = setTimeout(
                    () => reject(new Error(`Timed out after ${t.timeout}ms`)),
                    t.timeout,
                  );
                });
                try {
                  return await Promise.race([exec, timeout]);
                } finally {
                  clearTimeout(timerId!);
                }
              }
              return await exec;
            } catch (err: unknown) {
              const msg = err instanceof Error ? err.message : String(err);
              if (attempt >= maxAttempts) {
                return `[Tool Error] ${t.name}: ${msg}`;
              }
            }
          }
          // unreachable, but satisfies TS
          return `[Tool Error] ${t.name}: unknown failure`;
        } finally {
          if (semaphore) semaphore.release();
        }
      },
    });
  }
  return result as ToolSet;
}

/**
 * Same as toVercelTools but with a no-op execute.
 * Useful for tool planning where you need LLM tool selection
 * without actually executing tools.
 */
export function toVercelToolsNoop(tools: BaseTool[]): ToolSet {
  const result: Record<string, unknown> = {};
  for (const t of tools) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    result[t.name] = (vercelTool as any)({
      description: t.description,
      parameters: t.parameters,
      execute: async () => "",
    });
  }
  return result as ToolSet;
}
