# Agent Orchestration — Review Report

## Verdict: NEEDS_REWORK

---

## AC Review

- **AC1: PASS** — `AgentChatDelegate` interface is defined with correct duck-typed `chat(message, options?)` signature. `AgentOrchestrator` implements it explicitly (`implements AgentChatDelegate`). Tests in `delegate.test.ts` verify structural typing, nesting, and forwarding through nested orchestrators. The "forward chat to nested orchestrator" test (line 47) exercises the actual call path, not just compilation.

- **AC2: PASS** — Passthrough test in `orchestrator.test.ts` (line 39) verifies `delegate.chat` is called with exact arguments, content/usage/toolCalls are propagated. `phaseReached === "delegate"` and `orchestrationIntent === null` are both asserted. All THEN conditions are covered.

- **AC3: PASS** — `intent.test.ts` covers: first-pattern match, no-match returns `unknown` with confidence 0, first-match stops (duplicate-pattern test at line 31), empty pattern list. Five tests, thorough coverage.

- **AC4: PASS** — `LLMFallbackIntentResolver` tests verify: LLM not called on deterministic hit; LLM called on unknown; custom `parseResponse` honored; graceful fallback to `unknown` on JSON parse error. The LLM mock returns a controlled response and the test verifies the extracted intent object/confidence values, not just the mock's return — these are not tautologies.

- **AC5: PASS** — `executor.test.ts` tests: executor called + delegate skipped + `phaseReached === "direct_execution"` + `directExecutorUsed` name recorded; null-return fallthrough to delegate; canHandle-false skips executor; multiple executors tried in order and stopped at first non-null. All four THEN conditions from spec are covered.

- **AC6: PASS** — `pending.test.ts` tests: pending state intercepted (`phaseReached === "pending_confirmation"`); pending cleared after confirm; override disposition continues normal flow and clears pending. GIVEN/WHEN/THEN all exercised against real `InMemoryPendingStateManager`.

- **AC7: PASS** — `classifyConfirmationDisposition` tests cover: multiple confirm keywords ("好", "確認", "對", "yes", "ok"); multiple reject keywords ("不要", "取消", "no", "cancel"); unrelated messages return "override"; case-insensitive for English. Custom `confirmationClassifier` override is wired in `orchestrator.ts` (line 132) but there is no dedicated test asserting that a custom classifier provided to the orchestrator is actually called instead of the default. This is a minor gap but not blocking since the wiring is a one-liner and the default classifier is well-tested.

- **AC8: PASS** — `channel.test.ts` covers: full parseIncoming → chat → formatOutgoing pipeline; call order via tracking array; no-adapter throws correct error message; parsed options (userId, sessionId) passed through to delegate. All THEN conditions from spec are exercised.

- **AC9: NEEDS_REWORK** — The session-state integration test at `session-state.test.ts` line 110–128 ("should save updated session state after delegate response") contains a tautology assertion:
  ```typescript
  expect(state === null || state !== null).toBe(true);
  ```
  The comment even acknowledges this: "At minimum, we verify the call doesn't throw." This test passes regardless of implementation behavior — it will not catch a regression where session state is never saved. The spec requires that `presentedEntities` from `OrchestrationResult` be persisted to the store. The implementation (`orchestrator.ts` lines 263–273) saves state only when `delegateResult.sessionId` is set, but the test for entity tracking post-delegation doesn't actually verify any state was written. **This is a BLOCK.**

- **AC10: PASS** — `orchestrator.test.ts` (line 156–170) verifies all required fields: `traceId` is truthy and string; `phaseReached` is one of the four valid values; `intentResolved` key exists; `timings` is defined with numeric `total`; `directExecutorUsed` key exists; `delegateUsed` key exists. The `"delegateUsed" in result.decisionTrace` check at line 168 uses `toBeDefined()` rather than `toContain()`-style but the field presence check is equivalent. Adequate.

- **AC11: PASS** — `types.test.ts` exercises `DeterministicIntentResolver<MyIntent>`, `AgentOrchestrator<MyIntent>` with typed `Map<MyIntent, ...>` delegates key, `GenericIntentObject` built-ins, `IntentResult<MyIntent>` construction, and `BaseIntentResolver<MyIntent>` custom implementation. These compile and run. Generics coverage is thorough.

- **AC12: PASS** — Routing tests in `orchestrator.test.ts` (lines 91–153): intent matches `task_capture` → `taskAgent.chat()` called, `generalAgent` not called, `delegateUsed === "task_capture"`; intent in map but unknown falls back to default; delegates map absent routes to default with `delegateUsed === "default"`. All THEN conditions verified.

- **AC13: PASS** — `lifecycle.test.ts` covers: `beforeMessage` called with correct arguments; `afterMessage` called with result content; `onError` called with correct error instance and main error is re-thrown; hook error does not propagate (`beforeMessage` throws, main flow continues); call-order test verifies before → delegate → after sequence. Five tests, all meaningful.

- **AC14: PASS** — `result.test.ts` verifies all NaruResult fields present (content, blocked, usage with sub-fields, toolCalls); new orchestration fields present (orchestrationIntent, decisionTrace, pendingConfirmation); `orchestrationIntent` null without resolver; `decisionTrace` always defined; `pendingConfirmation` null by default; delegate content and toolCalls preserved exactly. Thorough.

---

## Naming Divergences Assessment

**Justified? Yes.**

Three documented divergences:

1. **`result.decisionTrace` vs spec `result.trace`** — Justified. `NaruResult` already has a `trace: Trace | null` field (the OpenTelemetry-style tracing system). Using `decisionTrace` avoids a collision on the same property name in `OrchestrationResult extends NaruResult`. The naming is semantically accurate.

2. **`result.orchestrationIntent` vs spec `result.intent`** — Justified. `NaruResult` already has `intent: IntentResult | null` where `IntentResult` has a completely different shape (`needsKnowledge`, `needsTools`, `raw`). Using `orchestrationIntent` avoids shadowing an existing field with a different type, which would break TypeScript's structural extension rule. Correct call.

3. **`OrchestratorIntent<T>` vs spec `IntentResult<T>`** — Justified. The existing `IntentResult` in `types.ts` has an unrelated shape. The implementation also exports `IntentResult` as a type alias for `OrchestratorIntent` within the orchestration module (intent.ts line 19), keeping a migration path open. No consumers are broken.

All three divergences are correctly documented in `review-brief.md` and are consistent throughout the codebase (no mixed usage found).

---

## Issues Found

- **[BLOCK]** `js/tests/orchestration/session-state.test.ts:127` — Tautology assertion `expect(state === null || state !== null).toBe(true)` in "should save updated session state after delegate response". The test does not verify that session state is actually written after a delegate response, which is the core THEN of AC9 ("entities stored into sessionStateStore"). A regression where the save logic is deleted would not be caught. The test needs to use a mock delegate that returns a `sessionId` (matching how `orchestrator.ts` line 264 triggers the save), then assert `state` is defined and has expected structure. — **AC9**

- **[WARN]** `js/tests/orchestration/lifecycle.test.ts:46` — `afterMessage` test asserts `calledWith.trace` (NaruResult's tracing trace) is defined with `toBeDefined()`, but the mock result has `trace: null`. This assertion passes because `toBeDefined()` treats `null` as defined (not `undefined`). The intent may have been to check `decisionTrace`, not `trace`. Non-blocking, but potentially misleading. — **AC13**

- **[WARN]** `js/tests/orchestration/orchestrator.test.ts:114` — AC12 routing test checks `taskAgent.chat` was called with `toHaveBeenCalled()` without verifying call arguments (message, options). Per anti-pattern criteria this is weak. The content check (`result.content === "task agent response"`) provides indirect verification, so not blocking. — **AC12**

- **[WARN]** `js/tests/orchestration/session-state.test.ts:105–108` — `orchestrator.chat` is called without a `sessionId` option, so `sessionId` in orchestrator is `null`. The `sessionStateStore` enrichment path at `orchestrator.ts:249` requires `sessionId` to be non-null. The test passes in `{ sessionId: "fresh-session" }` in one case but uses no sessionId here, meaning the sessionState path under test is never reached for the "save after delegate" scenario. Related to the BLOCK above.

- **[WARN]** `js/src/orchestration/executor.ts:14` — `BaseDirectExecutor.execute()` takes `Promise<OrchestrationResult | null>` as return type, meaning executors must construct a full `OrchestrationResult` including `decisionTrace`. This is an implementation burden — the `decisionTrace` is then overwritten by `orchestrator.ts:212` via `buildFinalResult`. This circular dependency is not wrong but is a design smell worth noting to future contributors.

- **[WARN]** AC7 gap (non-blocking): No test verifies that a custom `confirmationClassifier` provided to `AgentOrchestratorConfig` is actually invoked instead of the default `classifyConfirmationDisposition`. The wiring exists at `orchestrator.ts:132` but is untested.
