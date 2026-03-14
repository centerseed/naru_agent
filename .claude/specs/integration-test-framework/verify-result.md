# Verify Result: integration-test-framework

## Verification Date
2026-03-14

## Commands Run
```
cd /Users/wubaizong/接案/naru_agent/.claude/worktrees/integration-test-framework/js
npm run lint     # tsc --noEmit
npx vitest run
npm run build    # tsc && tsc -p tsconfig.cjs.json
```

## Results

### npm run lint
**Status: PASS**
No TypeScript errors. Zero output (clean exit).

### npx vitest run
**Status: PASS**

```
Test Files  18 passed | 7 skipped (25)
     Tests  96 passed | 39 skipped (135)
  Duration  1.25s
```

Skipped test files (7) are all integration tests that require `GOOGLE_GENERATIVE_AI_API_KEY` — correctly gated with `describeIf`. This is expected behavior.

### npm run build
**Status: PASS**
Both `tsc` and `tsc -p tsconfig.cjs.json` completed without errors.

---

## Fix Verification

### B1 — @ac16: `concurrent_users_must_all_succeed` baseline honored
- `loadBaseline()` is called inside the test.
- `baseline.concurrent_users_must_all_succeed` drives `minSuccess` calculation.
- With `concurrent_users_must_all_succeed: true`, all 3 requests must succeed.
- With `false`, 67% success is acceptable.
- **Verified: FIXED**

### N1 — `assertScenarioResult()` now throws on `trace_min_spans` and `has_stream_events`
- Both fields now have explicit `throw new Error(...)` guards in `scenario-runner.ts`.
- Any test accidentally passing these fields to `assertScenarioResult` will fail with a clear error.
- Existing tests (which use inline assertions for streaming and trace) are unaffected.
- **Verified: FIXED**

### N2 — Old `tests/integration/baselines/quality_baseline.json` deleted
- File confirmed deleted. `ls tests/integration/baselines/` shows no `quality_baseline.json`.
- `tests/integration/test_quality_baseline.py` updated: `BASELINE_PATH = Path(__file__).parent.parent / "shared" / "baselines" / "quality_baseline.json"`
- `tests/integration/test_capability_baseline.py` updated: same path.
- No remaining Python code references the old path.
- **Verified: FIXED**

### N3 — rag.json graph structure scenarios no longer misuse `tokens_max`
- `graph_min_entities` and `graph_min_relations` scenarios no longer have `"tokens_max": 5` and `"tokens_max": 4`.
- Both now have empty `"expect": {}` blocks with descriptive notes explaining inline baseline assertions.
- `assertScenarioResult` will not attempt to assert `result.usage.totalTokens <= 5` for these scenarios.
- **Verified: FIXED**

### N4 — @ac10 always-active skill has meaningful assertion
- Test now asserts `/你好|您好|歡迎|嗨|Hi|Hello|Greet/i.test(result.content)`.
- A regression where `alwaysActive` is ignored would omit greeting language and fail this check.
- **Verified: FIXED**
