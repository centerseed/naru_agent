import type { ModelMessage } from "ai";
import type { BaseSessionStore } from "./base.js";

/**
 * Redis-backed session store. Requires `ioredis` as optional dependency.
 */
export class RedisSessionStore implements BaseSessionStore {
  private redis: import("ioredis").default;
  private prefix: string;
  private ttlSeconds: number;

  constructor(
    redis: import("ioredis").default,
    prefix = "naru:session:",
    ttlSeconds = 86400,
  ) {
    this.redis = redis;
    this.prefix = prefix;
    this.ttlSeconds = ttlSeconds;
  }

  private key(sessionId: string): string {
    return `${this.prefix}${sessionId}`;
  }

  async get(sessionId: string): Promise<ModelMessage[] | null> {
    const data = await this.redis.get(this.key(sessionId));
    if (!data) return null;
    return JSON.parse(data) as ModelMessage[];
  }

  async save(sessionId: string, history: ModelMessage[]): Promise<void> {
    await this.redis.set(
      this.key(sessionId),
      JSON.stringify(history),
      "EX",
      this.ttlSeconds,
    );
  }

  async delete(sessionId: string): Promise<void> {
    await this.redis.del(this.key(sessionId));
  }
}
