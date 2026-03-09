"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.RedisSessionStore = void 0;
/**
 * Redis-backed session store. Requires `ioredis` as optional dependency.
 */
class RedisSessionStore {
    redis;
    prefix;
    ttlSeconds;
    constructor(redis, prefix = "naru:session:", ttlSeconds = 86400) {
        this.redis = redis;
        this.prefix = prefix;
        this.ttlSeconds = ttlSeconds;
    }
    key(sessionId) {
        return `${this.prefix}${sessionId}`;
    }
    async get(sessionId) {
        const data = await this.redis.get(this.key(sessionId));
        if (!data)
            return null;
        return JSON.parse(data);
    }
    async save(sessionId, history) {
        await this.redis.set(this.key(sessionId), JSON.stringify(history), "EX", this.ttlSeconds);
    }
    async delete(sessionId) {
        await this.redis.del(this.key(sessionId));
    }
}
exports.RedisSessionStore = RedisSessionStore;
