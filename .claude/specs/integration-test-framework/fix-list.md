# Fix List: integration-test-framework

## Blocking Issues

### B1 — @ac16: `concurrent_users_must_all_succeed` baseline value not honored — ✅ FIXED

**Location:** `js/tests/integration/test_quality.test.ts`, line 91

**Problem:**
The shared baseline (`tests/shared/baselines/quality_baseline.json`) declares:
```json
"concurrent_users_must_all_succeed": true
```
But the test hardcoded:
```typescript
expect(fulfilled.length).toBeGreaterThanOrEqual(2); // tolerates 1 failure out of 3
```
The baseline key was never read. The test contradicted the baseline contract.

**Fix Applied (Option A — Honor the baseline value):**
```typescript
const baseline = loadBaseline();
const mustAllSucceed = baseline.concurrent_users_must_all_succeed as boolean;
const minSuccess = mustAllSucceed ? requests.length : Math.ceil(requests.length * 0.67);
expect(fulfilled.length).toBeGreaterThanOrEqual(minSuccess);
```

---

## Non-Blocking Issues (should fix before merge)

### N1 — `assertScenarioResult()` missing `has_stream_events` and `trace_min_spans` implementations — ✅ FIXED

**Location:** `js/tests/integration/scenario-runner.ts`, after the `toolCalls_min_count` block

**Fix Applied:**
Added explicit `throw` guards for both unsupported fields. Any future test that calls `assertScenarioResult()` with `trace_min_spans` or `has_stream_events` will now receive a descriptive error instead of silently no-op'ing. Comments explain the correct approach (inline assertions for trace files and streaming events respectively).

---

### N2 — Old `tests/integration/baselines/quality_baseline.json` not deleted — ✅ FIXED

**Fix Applied:**
- Deleted `tests/integration/baselines/quality_baseline.json`.
- Updated `tests/integration/test_quality_baseline.py` to point `BASELINE_PATH` to `tests/shared/baselines/quality_baseline.json`.
- Updated `tests/integration/test_capability_baseline.py` to point `BASELINE_PATH` to `tests/shared/baselines/quality_baseline.json`.
- Verified no other Python test files referenced the old path.

---

### N3 — rag.json graph structure scenarios misuse `tokens_max` — ✅ FIXED

**Location:** `tests/shared/scenarios/rag.json`, scenarios `graph_min_entities` and `graph_min_relations`

**Fix Applied:**
Removed the `tokens_max` field from both scenarios. Replaced with:
- A descriptive `description` field noting the threshold comes from `quality_baseline.json`.
- A `note` field documenting that assertions are handled inline in `test_rag.test.ts` via `loadBaseline()`.
- An empty `expect: {}` block to satisfy the `Scenario` interface type.

This prevents `assertScenarioResult` from ever asserting `result.usage.totalTokens <= 5` (which would be nonsensical for entity counts).

---

### N4 — @ac10 always-active skill assertion is too shallow — ✅ FIXED

**Location:** `js/tests/integration/test_skills.test.ts`, lines 149-159

**Fix Applied:**
Added greeting language assertion after the existing content checks:
```typescript
const hasGreeting = /你好|您好|歡迎|嗨|Hi|Hello|Greet/i.test(result.content);
expect(hasGreeting).toBe(true);
```
A regression where `alwaysActive` is silently ignored will now cause this test to fail, since the prompt injection ("每次回覆開頭加上友善的問候語") would not be applied.
