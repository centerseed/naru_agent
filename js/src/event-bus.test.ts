import { describe, it, expect, vi } from "vitest";
import { EventBus } from "./event-bus.js";

describe("EventBus", () => {
  it("emits events to handlers", () => {
    const bus = new EventBus();
    const handler = vi.fn();
    bus.on("test", handler);
    bus.emit("test", { foo: "bar" });
    expect(handler).toHaveBeenCalledWith({ foo: "bar" });
  });

  it("removes handlers with off()", () => {
    const bus = new EventBus();
    const handler = vi.fn();
    bus.on("test", handler);
    bus.off("test", handler);
    bus.emit("test");
    expect(handler).not.toHaveBeenCalled();
  });

  it("swallows handler errors", () => {
    const bus = new EventBus();
    bus.on("test", () => { throw new Error("oops"); });
    const handler2 = vi.fn();
    bus.on("test", handler2);
    bus.emit("test");
    expect(handler2).toHaveBeenCalled();
  });
});
