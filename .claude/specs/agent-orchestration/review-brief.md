# Review Brief: agent-orchestration/python-port

## Implementation Approach

移植 JS `js/src/orchestration/` 模組到 Python，保持 1:1 邏輯對應，同時適配 Python 慣例。

### 架構決策

1. **同步 API** — 所有方法皆同步，與 `NaruAgent.chat()` 一致
2. **Protocol (PEP 544)** — `AgentChatDelegate` 使用 `Protocol`，NaruAgent 自動滿足（structural subtyping）
3. **dataclass 繼承** — `OrchestrationResult(NaruResult)` 用 dataclass field 擴展
4. **ABC** — `BaseDirectExecutor`, `BasePendingStateManager`, `BaseSessionStateStore` 用 ABC 強制實作
5. **`@runtime_checkable` Protocol** — `ChannelAdapter` 可做 `isinstance` 檢查
6. **snake_case** — 全部 Python 命名（`phase_reached`, `intent_resolved`, `direct_executor_used` 等）
7. **`time.monotonic()`** — 所有 timing 計算（秒，非毫秒）
8. **`uuid.uuid4()`** — 每次呼叫產生唯一 trace_id
9. **`TYPE_CHECKING` guard** — trace.py 用 `if TYPE_CHECKING` 引用 intent 類型，避免循環 import

### 4-Phase 路由邏輯

```
Phase 0: pending_state_manager + session_id → confirm/reject/override
Phase 1: intent_resolver → OrchestratorIntent
Phase 2: direct_executors[].can_handle() → execute() or fallthrough
Phase 3: delegates dict 路由 or default delegate
```

---

## AC Status

- [x] @ac1  — AgentChatDelegate Protocol 相容性（test_delegate.py, 4 tests）
- [x] @ac2  — 單一 agent 零開銷 passthrough（test_orchestrator.py, 6 tests）
- [x] @ac3  — DeterministicIntentResolver（test_intent.py, 4 tests）
- [x] @ac4  — LLMFallbackIntentResolver（test_intent.py, 4 tests）
- [x] @ac5  — DirectExecutor 快速路徑（test_executor.py, 5 tests）
- [x] @ac6  — PendingState 確認流程（test_pending.py, 6 tests）
- [x] @ac7  — PendingState 確認判定 CJK + 英文 regex（test_pending.py, 17 tests）
- [x] @ac8  — ChannelAdapter 訊息轉換（test_channel.py, 6 tests）
- [x] @ac9  — Session state entity tracking（test_session_state.py, 7 tests）
- [x] @ac10 — AgentDecisionTrace 完整性（test_orchestrator.py, 4 tests）
- [x] @ac11 — Generic typing 驗證（test_types.py, 6 tests）
- [x] @ac12 — Intent-to-delegate routing（test_orchestrator.py, 3 tests）
- [x] @ac13 — Lifecycle hooks（test_lifecycle.py, 6 tests）
- [x] @ac14 — OrchestrationResult 向後相容（test_result.py, 6 tests）

---

## Changed Files

### 新建檔案

| File | 說明 |
|------|------|
| `naru_agent/orchestration/__init__.py` | barrel export |
| `naru_agent/orchestration/orchestrator.py` | AgentOrchestrator + AgentChatDelegate + LifecycleHooks + AgentOrchestratorConfig |
| `naru_agent/orchestration/intent.py` | OrchestratorIntent, BaseIntentResolver, DeterministicIntentResolver, LLMFallbackIntentResolver |
| `naru_agent/orchestration/executor.py` | BaseDirectExecutor (ABC) |
| `naru_agent/orchestration/channel.py` | ChannelAdapter (Protocol), ChannelMessage |
| `naru_agent/orchestration/pending.py` | PendingState, BasePendingStateManager, InMemoryPendingStateManager, classify_confirmation_disposition |
| `naru_agent/orchestration/session_state.py` | AgentSessionState, BaseSessionStateStore, InMemorySessionStateStore |
| `naru_agent/orchestration/trace.py` | AgentDecisionTrace, OrchestrationPhase, OrchestrationTimings |
| `naru_agent/orchestration/result.py` | OrchestrationResult, PendingConfirmation |
| `tests/unit/orchestration/__init__.py` | test package |
| `tests/unit/orchestration/test_delegate.py` | @ac1 (4 tests) |
| `tests/unit/orchestration/test_result.py` | @ac14 (6 tests) |
| `tests/unit/orchestration/test_orchestrator.py` | @ac2, @ac10, @ac12 (13 tests) |
| `tests/unit/orchestration/test_intent.py` | @ac3, @ac4 (8 tests) |
| `tests/unit/orchestration/test_executor.py` | @ac5 (5 tests) |
| `tests/unit/orchestration/test_pending.py` | @ac6, @ac7 (12 tests + parametrize) |
| `tests/unit/orchestration/test_session_state.py` | @ac9 (7 tests) |
| `tests/unit/orchestration/test_channel.py` | @ac8 (6 tests) |
| `tests/unit/orchestration/test_lifecycle.py` | @ac13 (6 tests) |
| `tests/unit/orchestration/test_types.py` | @ac11 (6 tests) |

### 修改檔案

| File | 說明 |
|------|------|
| `naru_agent/__init__.py` | 新增 orchestration exports（try/except 保護，保持向後相容） |

---

## Verification Results

```
============================= test session starts ==============================
platform darwin -- Python 3.13.3, pytest-9.0.2, pluggy-1.6.0 -- /Users/wubaizong/接案/naru_agent/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/wubaizong/接案/naru_agent/.claude/worktrees/agent-orchestration-python
configfile: pyproject.toml
plugins: anyio-4.12.1, mock-3.15.1, asyncio-1.3.0

======================== 393 passed, 5 skipped in 1.14s ========================
```

- 新增 orchestration 測試：**98 tests**（全部通過）
- 既有測試：295 tests（全部通過，無 regression）
- 5 skipped：pre-existing（`GEMINI_API_KEY` 未設定，與本 PR 無關）
