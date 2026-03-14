# Fix List — Blocking Issues Only

## BLOCK-1: AC9 Tautology Test — Session State Save

**File:** `js/tests/orchestration/session-state.test.ts:110–128`
**Test name:** "should save updated session state after delegate response"

**Problem:**
The assertion `expect(state === null || state !== null).toBe(true)` is always true and provides zero regression protection. This test will pass even if the entire session-state-save code path is deleted.

**Root cause:** The mock delegate returns `makeMockNaruResult("...")` which has `sessionId: "sess-1"`, but `orchestrator.chat` is called with `{ sessionId: "sess-1" }` as options. The orchestrator save path at `orchestrator.ts:264` is:
```typescript
if (this.config.sessionStateStore && sessionId && delegateResult.sessionId) {
```
Both conditions must be true. The current test setup does satisfy them — the save code does run — but the assertion doesn't check the outcome.

**Required fix:**
```typescript
it("should save updated session state after delegate response", async () => {
  const store = new InMemorySessionStateStore();

  const orchestrator = new AgentOrchestrator({
    delegate: {
      // Return a sessionId to trigger the save path
      chat: async () => makeMockNaruResult("Here are your tasks: Task A, Task B"),
      // makeMockNaruResult already sets sessionId: "sess-1"
    },
    sessionStateStore: store,
  });

  await orchestrator.chat("list tasks", { sessionId: "sess-1" });

  const state = await store.get("sess-1");
  // State MUST be non-null — the orchestrator should have saved it
  expect(state).not.toBeNull();
  expect(state?.sessionId).toBe("sess-1");
  expect(state?.updatedAt).toBeGreaterThan(0);
});
```

**AC covered:** AC9

---

> No other blocking issues. See `review-report.md` for non-blocking warnings.
