"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.EventBus = void 0;
class EventBus {
    handlers = new Map();
    on(event, handler) {
        if (!this.handlers.has(event)) {
            this.handlers.set(event, new Set());
        }
        this.handlers.get(event).add(handler);
    }
    off(event, handler) {
        this.handlers.get(event)?.delete(handler);
    }
    emit(event, data) {
        const handlers = this.handlers.get(event);
        if (!handlers)
            return;
        for (const handler of handlers) {
            try {
                handler(data);
            }
            catch {
                // swallow handler errors
            }
        }
    }
    removeAllListeners(event) {
        if (event) {
            this.handlers.delete(event);
        }
        else {
            this.handlers.clear();
        }
    }
}
exports.EventBus = EventBus;
