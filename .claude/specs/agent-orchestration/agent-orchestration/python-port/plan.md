# Plan Brief: agent-orchestration/python-port

## Goal

將 JS orchestration 模組完整移植到 Python，讓 Python 版的 naru-agent 也具備 4-phase routing + 多 agent 協作能力。

## BDD Spec

→ Behavioral contract: `docs/bdd/agent-orchestration.feature`
  所有 AC 場景皆適用（@ac1 ~ @ac14），除了 @ac11（TypeScript generics 編譯驗證）改為 Python typing 驗證
→ Parent dev brief: `.claude/specs/agent-orchestration/spec.md`

## Metadata

- affected: python
- db_migration: false
- deploy_required: false

## 設計決策

### 1. 同步 vs 非同步

Python 的 `NaruAgent.chat()` 是**同步**的。`AgentOrchestrator` 也應該是同步的：

```python
class AgentOrchestrator:
    def chat(self, message: str, *, user_id: str | None = None, session_id: str | None = None) -> OrchestrationResult:
        ...
```

Pending/session state manager 的 store 方法也用同步（與 Python codebase 一致），但保留 ABC 讓使用者可以自行實作非同步版本。

### 2. AgentChatDelegate → Protocol

JS 用 interface（duck typing），Python 用 `Protocol`：

```python
from typing import Protocol

class AgentChatDelegate(Protocol):
    def chat(self, message: str, *, user_id: str | None = None, session_id: str | None = None) -> NaruResult:
        ...
```

`NaruAgent` 自然滿足此 Protocol（structural subtyping），不需修改。

### 3. Generics

JS 的 `<T extends string>` → Python 的 `Generic[T]` + `TypeVar`：

```python
T = TypeVar("T", bound=str)

@dataclass
class OrchestratorIntent(Generic[T]):
    object: T
    confidence: float
    requires_confirmation: bool = False
```

### 4. OrchestrationResult 擴展 NaruResult

Python 用 dataclass 繼承：

```python
@dataclass
class OrchestrationResult(NaruResult):
    decision_trace: AgentDecisionTrace = field(default_factory=...)
    pending_confirmation: PendingConfirmation | None = None
    orchestration_intent: OrchestratorIntent | None = None
```

### 5. 確認分類器（Confirmation Classifier）

與 JS 相同，使用 CJK + 英文 regex 模式：

```python
CONFIRM_PATTERN = re.compile(r"^(好|確認|對|yes|y|ok|好的|是|沒問題|sure|confirm)$", re.IGNORECASE)
REJECT_PATTERN = re.compile(r"^(不要|取消|no|n|不|cancel|否|算了|不行|reject)$", re.IGNORECASE)
```

### 6. chat() 參數映射

JS 的 `ChatOptions` 是 object，Python 的 `NaruAgent.chat()` 用 keyword args：

| JS | Python |
|----|--------|
| `options.userId` | `user_id` |
| `options.sessionId` | `session_id` |

`AgentOrchestrator.chat()` 額外接受 `**kwargs` 傳給 delegate，保持擴展性。

## AC → Test Mapping

| AC Tag | Scenario Name | Test Type | Test File |
|--------|--------------|-----------|-----------|
| @ac1 | AgentChatDelegate Protocol 相容性 | unit | tests/unit/orchestration/test_delegate.py |
| @ac2 | 單一 agent 零開銷 passthrough | unit | tests/unit/orchestration/test_orchestrator.py |
| @ac3 | DeterministicIntentResolver | unit | tests/unit/orchestration/test_intent.py |
| @ac4 | LLMFallbackIntentResolver | unit | tests/unit/orchestration/test_intent.py |
| @ac5 | DirectExecutor 快速路徑 | unit | tests/unit/orchestration/test_executor.py |
| @ac6 | PendingState 確認流程 | unit | tests/unit/orchestration/test_pending.py |
| @ac7 | PendingState 確認判定 | unit | tests/unit/orchestration/test_pending.py |
| @ac8 | ChannelAdapter 訊息轉換 | unit | tests/unit/orchestration/test_channel.py |
| @ac9 | Session state entity tracking | unit | tests/unit/orchestration/test_session_state.py |
| @ac10 | AgentDecisionTrace 完整性 | unit | tests/unit/orchestration/test_orchestrator.py |
| @ac11 | Generic typing 驗證 | unit | tests/unit/orchestration/test_types.py |
| @ac12 | Intent-to-delegate routing | unit | tests/unit/orchestration/test_orchestrator.py |
| @ac13 | Lifecycle hooks | unit | tests/unit/orchestration/test_lifecycle.py |
| @ac14 | OrchestrationResult 向後相容 | unit | tests/unit/orchestration/test_result.py |

## Architecture

```
naru_agent/orchestration/           ← 全部新增
├── __init__.py                     ← public exports
├── orchestrator.py                 ← AgentOrchestrator（主類）
├── intent.py                       ← BaseIntentResolver, Deterministic, LLMFallback, OrchestratorIntent
├── executor.py                     ← BaseDirectExecutor (ABC)
├── channel.py                      ← ChannelAdapter (Protocol)
├── pending.py                      ← BasePendingStateManager, InMemoryPendingStateManager
├── session_state.py                ← AgentSessionState, BaseSessionStateStore, InMemorySessionStateStore
├── trace.py                        ← AgentDecisionTrace, OrchestrationPhase
└── result.py                       ← OrchestrationResult, PendingConfirmation
```

## Files to Change

### 新建檔案

| File | AC | 說明 |
|------|----|------|
| `naru_agent/orchestration/__init__.py` | all | barrel export |
| `naru_agent/orchestration/orchestrator.py` | @ac1,@ac2,@ac5,@ac6,@ac10,@ac12,@ac13 | 主 orchestrator，4-phase routing |
| `naru_agent/orchestration/intent.py` | @ac3,@ac4,@ac11 | 意圖解析系統 |
| `naru_agent/orchestration/executor.py` | @ac5 | DirectExecutor ABC |
| `naru_agent/orchestration/channel.py` | @ac8 | ChannelAdapter Protocol |
| `naru_agent/orchestration/pending.py` | @ac6,@ac7 | Pending state + confirmation classifier |
| `naru_agent/orchestration/session_state.py` | @ac9 | Session state store |
| `naru_agent/orchestration/trace.py` | @ac10 | Decision trace 型別 |
| `naru_agent/orchestration/result.py` | @ac14 | OrchestrationResult dataclass |
| `tests/unit/orchestration/__init__.py` | — | test package |
| `tests/unit/orchestration/test_orchestrator.py` | @ac2,@ac10,@ac12 | orchestrator 核心測試 |
| `tests/unit/orchestration/test_intent.py` | @ac3,@ac4 | intent resolver 測試 |
| `tests/unit/orchestration/test_executor.py` | @ac5 | executor 測試 |
| `tests/unit/orchestration/test_pending.py` | @ac6,@ac7 | pending state 測試 |
| `tests/unit/orchestration/test_channel.py` | @ac8 | channel adapter 測試 |
| `tests/unit/orchestration/test_session_state.py` | @ac9 | session state 測試 |
| `tests/unit/orchestration/test_lifecycle.py` | @ac13 | lifecycle hooks 測試 |
| `tests/unit/orchestration/test_result.py` | @ac14 | result 相容性測試 |
| `tests/unit/orchestration/test_delegate.py` | @ac1 | Protocol 相容性測試 |
| `tests/unit/orchestration/test_types.py` | @ac11 | Generic typing 測試 |

### 修改檔案

| File | 說明 |
|------|------|
| `naru_agent/__init__.py` | 新增 orchestration module re-export |

## Files That Must NOT Change

| File | 原因 |
|------|------|
| `naru_agent/agent.py` | NaruAgent 內部不改，它已自然滿足 AgentChatDelegate Protocol |
| `naru_agent/intent/base.py` | 現有 IntentResult 是 NaruAgent 內部的概念，與 OrchestratorIntent 不同 |
| `naru_agent/tools/base.py` | 不改 |
| `naru_agent/skills/*.py` | 不改 |

## Implementation Notes

### Reference Implementation

JS 版本：`js/src/orchestration/orchestrator.ts` — 直接參照，1:1 邏輯移植

### Key Patterns

- **命名慣例**：snake_case（Python），`phase_reached` 而非 `phaseReached`
- **型別**：dataclass + Protocol（不用 Pydantic，與 NaruResult 一致）
- **錯誤處理**：lifecycle hooks 的錯誤 catch + log，不 rethrow（同 JS）
- **UUID**：`uuid.uuid4()` 取代 JS 的 `uuidv4()`
- **時間計量**：`time.monotonic()` 計算 timings（非 `time.time()`）

### Reuse

- `NaruResult`（from agent.py）— OrchestrationResult 繼承
- 測試 pattern（from tests/unit/test_naru_agent.py）— mock 風格一致

### 與 JS 版的差異

| 面向 | JS | Python |
|------|-----|--------|
| async/sync | async (Promise) | sync |
| interface | TypeScript interface | Protocol (PEP 544) |
| generics | `<T extends string>` | `TypeVar("T", bound=str)` + `Generic[T]` |
| `ChatOptions` | `{ userId, sessionId }` | keyword args: `user_id`, `session_id` |
| NaruResult fields | `intent` (IntentResult) | `intent` (IntentResult) — 保持不變 |
| 新增 field | `orchestrationIntent` | `orchestration_intent` (snake_case) |
| `processChannel` | method on class | `process_channel` (snake_case) |

## Out of Scope

- NaruAgent 內部重構 — 不改
- 具體 channel 實作（LINE/Slack）— 只提供介面
- 具體 intent/executor 實作 — 只提供框架類別
- Agent handoff（response-level）— 不支援
- Streaming — AgentOrchestrator 不暴露 streaming

## Suggested Build Sequence

1. **Types first**：`trace.py` → `result.py` → `intent.py` → `executor.py` → `channel.py` → `pending.py` → `session_state.py`
2. **Orchestrator**：`orchestrator.py`（依賴所有 types）
3. **Exports**：`orchestration/__init__.py` → `naru_agent/__init__.py`
4. **Tests**：按 AC 順序寫測試

## PAUSE Gates

- [ ] DB migration: no
- [ ] Test data deletion: no
- [ ] Deployment: no（library，不需 deploy）
