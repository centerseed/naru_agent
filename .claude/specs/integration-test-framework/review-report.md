# Review Report: integration-test-framework

## Spec Review Verdict: PASS

All blocking and non-blocking issues have been resolved. See `fix-list.md` for details of each fix and `verify-result.md` for verification results.

---

### AC-by-AC Review

**@ac1 — Shared scenario files created in `tests/shared/`**
PASS (with caveat). All required scenario JSON files exist at `tests/shared/scenarios/`. However, there is no dedicated `it()` block that verifies each file loads correctly and contains a `scenarios` array. Validation is implicit: `loadScenarios()` is called at module top level and will throw if a file is missing or malformed, causing the test file to fail to load. This is acceptable as a smoke test, but a dedicated `it("shared scenario files are loadable")` would be more robust. Not a blocker.

**@ac2 — Merged baseline in `tests/shared/baselines/quality_baseline.json`**
PASS (with caveat). The baseline file exists and contains all required keys. Same implicit-load-only caveat as @ac1. Not a blocker.

**@ac3 — Single tool selection + chitchat no-tool**
PASS. Three test cases: `single_tool_selection` asserts `toolCalls_contains: ["calculate_shipping_cost"]`; `chitchat_no_tools` asserts `toolCalls_max_count: 0`; `tool_result_in_response` checks content keywords from tool output. Edge case (chitchat) is present. Uses real LLM with `describeIf`. GIVEN/WHEN/THEN all properly wired.

**@ac4 — Multi-tool chaining**
PASS. Two scenarios: `multi_tool_chaining` verifies `search_products` plus at least one of `get_product_detail`/`check_inventory`, and ordering is verified via `callLog`. `tool_chain_order` verifies search→inventory→order sequence. Edge cases via call-log ordering assertion.

**@ac5 — Parallel tool execution**
PASS. `parallel_tool_execution` scenario asserts at least one of the requested tools. Edge case test verifies tool params are non-null when called. Would benefit from a stronger parallel-execution assertion (e.g. timing-based), but not a blocker.

**@ac6 — Vector knowledge retrieval**
PASS. `InMemoryKnowledgeStore` is ingested with real facts before each test (`beforeEach` with `batchIngest`). Three test cases: ChromaDB keyword, fact extraction keywords, refusal for unknown info. The refusal test's logic (`!hasPrice || hasRefusal`) correctly allows a response that either lacks price info OR contains a refusal phrase. Edge case (refusal) is present.

**@ac7 — Knowledge graph query**
PASS. `GraphKnowledgeStore` is ingested with `GRAPH_TEXT` in `beforeEach`. Four tests: min entities, min relations, medication traversal, stress traversal. Graph structure tests read from `loadBaseline()`. Real LLM required (describeIf).

**@ac8 — Keyword trigger + no-trigger**
PASS. Two tests: `keyword_trigger` verifies `get_weather` in `toolCalls`; `no_trigger` verifies `get_weather` NOT in `toolCalls`. Weather skill is constructed from the scenario JSON definitions. Edge case (no-trigger) present.

**@ac9 — Skill injects extra tool**
PASS. Skill triggers on "高雄", `get_weather` appears in `toolCalls`, and response contains "高雄". Both the injection mechanism and the content outcome are verified.

**@ac10 — Always-active skill**
PASS. Previously shallow (`content_not_empty` only). Now asserts that the response contains greeting language matching `/你好|您好|歡迎|嗨|Hi|Hello|Greet/i`, verifying the prompt injection ("每次回覆開頭加上友善的問候語") had a visible effect. A regression where `alwaysActive` is silently ignored would now be caught.

**@ac11 — Single agent passthrough**
PASS. Two tests: basic passthrough checks `content.length > 0`; options passthrough verifies `userId` and `sessionId` are forwarded to the delegate. Uses mock delegate correctly per spec note.

**@ac12 — Intent routing**
PASS. Four tests: order routing, product routing, default fallback, and `decisionTrace.delegateUsed` field. All routing assertions check delegate name in content (mock delegates include `[name]` prefix). Covers positive routing and no-match fallback.

**@ac13 — Direct executor**
PASS. Two tests: `ping` direct executor returns "pong" and `decisionTrace.phaseReached === "direct_execution"`; null executor falls through to delegate. Both the bypass path and fallthrough path are tested.

**@ac14 — Multi-step confirmation**
PASS. Three tests: `setPending` + `chat("確認")` verifies `phaseReached === "pending_confirmation"` and content contains `delete_orders`; rejection clears pending state (verified via `getPending`); override clears pending and continues normal flow. The assertion that `result.content.contains("delete_orders")` is valid — the orchestrator produces `"Confirmed: ${pending.type}"`.

**@ac15 — Token usage**
PASS. Three tests read from the shared baseline: simple chat budget, 16-tool call budget, and presence of all three usage fields. Baseline keys are consumed correctly.

**@ac16 — Concurrent user isolation**
PASS. Previously BLOCKED. The test now reads `baseline.concurrent_users_must_all_succeed` and computes `minSuccess` accordingly. With the current baseline value of `true`, all 3 concurrent requests must succeed. The baseline contract is fully honored.

**@ac17 — Response quality**
PASS. Three tests: tool result in response (verifies `track_shipment` called and content contains location keywords); language instruction (checks for Chinese Unicode characters); no-hallucinated-tools (verifies all `result.toolCalls` names exist in `ALL_TOOLS` set).

**@ac18 — Trace completeness**
PASS. Five tests: required fields (`traceId`, `input`, `output`, `startTime`, `endTime`, `usage`, `spans`); LLM span present; timing consistency (span bounds within trace bounds); intent span when classifier used; JSONL parseability. `traceId` cross-verified against `result.traceId`.

**@ac19 — Memory extraction**
PASS. Two tests: `MemoryManager.add()` extracts ≥ baseline `memory_min_extracted_facts` items, and at least one contains a known fact keyword; cross-turn session recall of peanut allergy. Both the extraction mechanism and the cross-turn recall path are tested.

**@ac20 — Long conversation compression**
PASS. Two tests: single key fact (March 15 deadline) survives compression; multi-fact retention ratio ≥ `compression_retention_min_ratio` from baseline. Compression is triggered by exceeding `compressionThresholdRounds`. The multi-fact test correctly computes a ratio rather than requiring 100% recall.

**@ac21 — Guardrails input protection**
PASS. Four tests run without API key: English keyword block, Chinese keyword block, safe order query passes (blocked === false), shopping query passes. `KeywordGuardrail` is constructed from the shared scenario's `blocked_patterns`. Both block and allow paths covered.

**@ac22 — Streaming events**
PASS (with note). Four streaming tests check for `text-delta` events and non-empty accumulated content. The `has_stream_events` and `trace_min_spans` DSL fields now throw if passed to `assertScenarioResult()` instead of silently no-op'ing. The DSL contract is now honest: any scenario that includes these fields must use inline assertions rather than the shared runner helper.

---

### Issues Resolved

#### Previously BLOCKING — Now FIXED

**B1 — @ac16: `concurrent_users_must_all_succeed` baseline not honored**
- FIXED. `test_quality.test.ts` now reads `baseline.concurrent_users_must_all_succeed` and enforces 100% success when `true`.

#### Previously NON-BLOCKING — Now FIXED

**N1 — `assertScenarioResult()` missing `has_stream_events` and `trace_min_spans` implementations**
- FIXED. Both fields now throw a descriptive error if passed to `assertScenarioResult()`. No more silent no-op.

**N2 — `tests/integration/baselines/quality_baseline.json` not deleted**
- FIXED. File deleted. Python tests updated to reference `tests/shared/baselines/quality_baseline.json`.

**N3 — rag.json graph structure scenarios misuse `tokens_max` field**
- FIXED. `tokens_max` removed from both structural scenarios. Replaced with empty `expect: {}` and descriptive `note` fields.

**N4 — @ac10 always-active skill assertion is too shallow**
- FIXED. Greeting language regex assertion added. Regression where `alwaysActive` is silently ignored would now fail the test.
