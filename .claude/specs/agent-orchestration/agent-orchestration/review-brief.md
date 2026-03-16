# Agent Orchestration — Review Brief

## Implementation Approach Summary

Implemented the full `AgentOrchestrator` system as a new `js/src/orchestration/` module. The orchestrator wraps any `AgentChatDelegate` (duck-typed interface — NaruAgent satisfies it structurally) and adds a 4-phase routing pipeline:

- **Phase 0**: Pending confirmation — checks `pendingStateManager` before processing; classifies user message disposition (confirm/reject/override)
- **Phase 1**: Intent resolution — calls `intentResolver.resolve()` if configured; supports `DeterministicIntentResolver` (fast regex pattern matching) and `LLMFallbackIntentResolver` (deterministic + LLM fallback chain)
- **Phase 2**: Direct execution — tries `directExecutors[]` in order; skips delegate LLM if an executor handles the intent
- **Phase 3**: Delegate routing — selects from `delegates` map by `intent.object` or falls back to default `delegate`

Key design decisions:
- `OrchestrationResult extends NaruResult` — preserving full backward compatibility. The NaruResult `trace` (tracing system Trace) is preserved; orchestration trace is in `decisionTrace: AgentDecisionTrace`
- Renamed orchestration intent type to `OrchestratorIntent<T>` to avoid name collision with the existing `IntentResult` from `types.ts` (which has `needsKnowledge/needsTools/raw` shape)
- Orchestration-resolved intent exposed as `orchestrationIntent` on `OrchestrationResult`
- TypeScript generics throughout: `AgentOrchestrator<T>`, `DeterministicIntentResolver<T>`, `BaseDirectExecutor<T>`, `OrchestratorIntent<T>`

## Reference Implementation Used

- `js/src/intent/llm-classifier.ts` — pattern for classifier classes
- `js/src/skills/base.ts` — pattern for interface + factory function style
- `js/src/agent.test.ts` — test patterns (describe/it, vi.fn() mocks, mock LanguageModel shape)
- `js/src/session/` — InMemory store pattern

## Naming Conventions Followed

- Files: `kebab-case.ts` (e.g., `session-state.ts`, `orchestrator.ts`)
- Classes: `PascalCase` (e.g., `AgentOrchestrator`, `DeterministicIntentResolver`)
- Interfaces: `PascalCase` with `Base` prefix for abstract (e.g., `BasePendingStateManager`)
- InMemory implementations: `InMemory` prefix (e.g., `InMemoryPendingStateManager`)
- Test files: `kebab-case.test.ts`
- Test naming: `it("should <expected> when <condition>")`
- Exports: named exports only, no default exports

## AC Status

- [x] AC1: AgentChatDelegate interface — NaruAgent structurally satisfies it; AgentOrchestrator is nestable
- [x] AC2: Minimum single-agent passthrough — delegate.chat() called with same args; returns OrchestrationResult with all NaruResult fields; trace.phaseReached = "delegate"
- [x] AC3: DeterministicIntentResolver — first-match pattern, returns unknown on no match
- [x] AC4: LLMFallbackIntentResolver — skips LLM when deterministic matches; calls LLM on unknown
- [x] AC5: DirectExecutor fast path — executor.execute() called; delegate skipped; fallthrough on null return
- [x] AC6: PendingState confirmation flow — Phase 0 intercepts; clears pending; phaseReached = "pending_confirmation"
- [x] AC7: Confirmation disposition — classifyConfirmationDisposition() classifies confirm/reject/override
- [x] AC8: ChannelAdapter message transformation — processChannel() calls parseIncoming → chat → formatOutgoing
- [x] AC9: AgentSessionState entity tracking — session state enriched into options for delegate; InMemorySessionStateStore provided
- [x] AC10: AgentDecisionTrace completeness — traceId, phaseReached, intentResolved, timings, directExecutorUsed, delegateUsed all present
- [x] AC11: Generic intent types — DeterministicIntentResolver<MyIntent>, AgentOrchestrator<MyIntent>, delegates map key typed
- [x] AC12: Intent-to-delegate routing — delegates map routes by intent.object; unknown falls back to default delegate; trace.delegateUsed set
- [x] AC13: Lifecycle hooks — beforeMessage/afterMessage/onError all fire; hook errors do not affect main flow
- [x] AC14: OrchestrationResult backward compat — all NaruResult fields preserved; new fields are additions only

## Changed Files

### Created
- `js/src/orchestration/orchestrator.ts` — AgentOrchestrator main class + AgentChatDelegate interface
- `js/src/orchestration/intent.ts` — OrchestratorIntent<T>, DeterministicIntentResolver, LLMFallbackIntentResolver
- `js/src/orchestration/executor.ts` — BaseDirectExecutor<T> interface
- `js/src/orchestration/channel.ts` — ChannelAdapter<TIn, TOut> interface
- `js/src/orchestration/pending.ts` — InMemoryPendingStateManager, classifyConfirmationDisposition
- `js/src/orchestration/session-state.ts` — InMemorySessionStateStore, AgentSessionState
- `js/src/orchestration/trace.ts` — AgentDecisionTrace type
- `js/src/orchestration/result.ts` — OrchestrationResult type
- `js/src/orchestration/index.ts` — barrel export
- `js/tests/orchestration/orchestrator.test.ts` — AC1, AC2, AC10, AC12
- `js/tests/orchestration/intent.test.ts` — AC3, AC4
- `js/tests/orchestration/executor.test.ts` — AC5
- `js/tests/orchestration/pending.test.ts` — AC6, AC7
- `js/tests/orchestration/session-state.test.ts` — AC9
- `js/tests/orchestration/channel.test.ts` — AC8
- `js/tests/orchestration/lifecycle.test.ts` — AC13
- `js/tests/orchestration/result.test.ts` — AC14
- `js/tests/orchestration/delegate.test.ts` — AC1
- `js/tests/orchestration/types.test.ts` — AC11

### Modified
- `js/src/index.ts` — added orchestration module re-exports
- `js/vitest.config.ts` — added `tests/**/*.test.ts` to include pattern

### Not Modified (as required)
- `js/src/agent.ts` — untouched
- `js/src/tools/base.ts` — untouched
- `js/src/skills/*.ts` — untouched

## Verification Command Results

```
$ npm run lint && npx vitest run && npm run build

> naru-agent-js@0.1.1 lint
> tsc --noEmit

 RUN  v2.1.9 /...agent-orchestration/js

 ✓ tests/orchestration/intent.test.ts (9 tests) 4ms
 ✓ tests/orchestration/executor.test.ts (4 tests) 3ms
 ✓ tests/orchestration/pending.test.ts (10 tests) 3ms
 ✓ tests/orchestration/session-state.test.ts (6 tests) 4ms
 ✓ tests/orchestration/orchestrator.test.ts (9 tests) 7ms
 ✓ tests/orchestration/types.test.ts (5 tests) 6ms
 ✓ tests/orchestration/channel.test.ts (4 tests) 3ms
 ✓ src/agent.test.ts (5 tests) 89ms
 ✓ src/memory/manager.test.ts (3 tests) 2ms
 ✓ tests/orchestration/result.test.ts (6 tests) 4ms
 ✓ tests/orchestration/lifecycle.test.ts (5 tests) 4ms
 ✓ src/skills/registry.test.ts (3 tests) 2ms
 ✓ tests/orchestration/delegate.test.ts (4 tests) 8ms
 ↓ tests/integration/test_capability_baseline.test.ts (16 tests | 16 skipped)
 ↓ tests/integration/test_quality_baseline.test.ts (16 tests | 16 skipped)
 ✓ src/guardrails/keyword.test.ts (3 tests) 1ms
 ✓ src/event-bus.test.ts (3 tests) 3ms
 ✓ src/tools/base.test.ts (2 tests) 1ms

 Test Files  16 passed | 2 skipped (18)
      Tests  81 passed | 32 skipped (113)
   Duration  1.05s

> naru-agent-js@0.1.1 build
> tsc && tsc -p tsconfig.cjs.json
```
