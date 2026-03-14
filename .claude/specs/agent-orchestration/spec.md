# Spec: agent-orchestration

## Goal

為 naru-agent-js 新增 Orchestration 層，讓 NaruAgent 從「單一 agent」升級為「可組合的 agent 協作框架」。從最小配置（single delegate passthrough）到最複雜（Swarm-like 多 agent 路由 + intent routing + channel adapter），全部由同一個 `AgentOrchestrator` 類別涵蓋。

## BDD Spec
> Full behavioral contract: `docs/bdd/agent-orchestration.feature`
> All acceptance criteria (Given/When/Then) are defined there by @ac tag.
> This brief adds only the technical context needed to implement them.

## Metadata
- affected: [js]
- db_migration: false
- deploy_required: false

## Context

### 設計來源
參考 Naruvia `/api/src/application/use-cases/agent/` 的以下模式：
- `agent-orchestrator.ts` — 4 階段路由（pending → intent → direct execute → delegate）
- `agent-intent-resolver.ts` — 兩層意圖解析（deterministic + LLM fallback）
- `direct-executor.ts` — 高信心度操作跳過 LLM
- `channel-adapter.ts` — channel 抽象（LINE/API/Slack）
- `agent-session-state.ts` — entity tracking + 指代消解
- `lifecycle-aware-agent.ts` — lifecycle hooks + logging

### 目標使用情境

**Minimum（單一 agent）**：
```typescript
const orchestrator = new AgentOrchestrator({ delegate: myNaruAgent })
const result = await orchestrator.chat("Hello")
// 等同 myNaruAgent.chat("Hello")，零開銷
```

**Medium（Naruvia-like intent routing）**：
```typescript
const orchestrator = new AgentOrchestrator({
  delegate: naruAgent,
  intentResolver: new LLMFallbackIntentResolver({
    primary: new DeterministicIntentResolver([
      { pattern: /^整理/, intent: { object: "reorganize", confidence: 1.0 } },
    ]),
    fallbackAgent: classifierAgent,
  }),
  directExecutors: [myTaskExecutor],
  sessionStateStore: new InMemorySessionStateStore(),
  pendingStateManager: new InMemoryPendingStateManager(),
})
```

**Maximum（Swarm-like 多 agent）**：
```typescript
const orchestrator = new AgentOrchestrator({
  delegate: generalAgent,                 // fallback
  delegates: new Map([
    ["task_capture", taskAgent],          // 專門處理任務記錄
    ["calendar_query", calendarAgent],    // 專門處理行事曆
  ]),
  intentResolver: myIntentResolver,
  channelAdapter: new LineChannelAdapter(redisClient),
})
```

### 架構層級
```
js/src/orchestration/           ← 全部新增
├── orchestrator.ts             ← AgentOrchestrator（主類）
├── intent.ts                   ← BaseIntentResolver, Deterministic, LLMFallback, GenericIntentObject
├── executor.ts                 ← BaseDirectExecutor
├── channel.ts                  ← ChannelAdapter<TIn, TOut>
├── pending.ts                  ← BasePendingStateManager, InMemoryPendingStateManager
├── session-state.ts            ← AgentSessionState, BaseSessionStateStore, InMemorySessionStateStore
├── trace.ts                    ← AgentDecisionTrace
├── result.ts                   ← OrchestrationResult
└── index.ts                    ← public exports
```

### 與現有 NaruAgent 的關係
- `NaruAgent` API 完全不變
- `NaruAgent` 自然滿足 `AgentChatDelegate` 介面（duck typing：有 `chat(message, options)` 方法即可）
- `AgentOrchestrator` 是可選的新層，不影響現有用戶
- `AgentOrchestrator` 自身也滿足 `AgentChatDelegate`，可以巢狀組合

---

## Phase Breakdown

Suggested implementation order — each phase becomes one `/ship` task:

| Phase | Name | ACs | Dependencies | Notes |
|-------|------|-----|--------------|-------|
| 1 | Core Types & Passthrough | @ac1, @ac2, @ac14 | none | Start here — interfaces + minimal orchestrator |
| 2 | Intent Resolution | @ac3, @ac4, @ac11 | Phase 1 | Deterministic + LLM fallback + generics |
| 3 | Direct Execution & Multi-Agent | @ac5, @ac12 | Phase 2 | DirectExecutor + delegates map |
| 4 | State Management | @ac6, @ac7, @ac9 | Phase 1 | PendingState + SessionState |
| 5 | Channel & Lifecycle | @ac8, @ac13, @ac10 | Phase 1 | ChannelAdapter + hooks + trace |

**Sizing guidance:** Each phase is 2-3 ACs, completable in one `/ship` run.
**Ordering:** Phase 1 must be first (defines interfaces). Phases 2-5 can be done in any order after Phase 1.
**Critical path:** Phase 1 → Phase 2 → Phase 3 (intent → executor → multi-agent depends on intent types).

---

## Acceptance Criteria (BDD)

### AC1: AgentChatDelegate 介面定義
- **GIVEN** 框架定義 `AgentChatDelegate` 介面（含 `chat(message, options?) → Promise<NaruResult>`）
- **WHEN** 一個 NaruAgent 實例傳入 AgentOrchestrator
- **THEN** TypeScript 編譯無型別錯誤（NaruAgent 結構上滿足 AgentChatDelegate）
- **THEN** AgentOrchestrator 自身也滿足 AgentChatDelegate（可巢狀）
- **Test**: unit
- **Platform**: js

### AC2: Minimum single-agent passthrough
- **GIVEN** `new AgentOrchestrator({ delegate: mockAgent })`，不設任何 resolver/executor
- **WHEN** `orchestrator.chat("Hello")` 被呼叫
- **THEN** `mockAgent.chat("Hello")` 被呼叫且參數完整傳遞
- **THEN** 返回的 `OrchestrationResult` 包含 delegate 的 content、usage、toolCalls
- **THEN** `result.trace.phaseReached === "delegate"`
- **THEN** `result.intent === null`（無 resolver）
- **Test**: unit
- **Platform**: js

### AC3: DeterministicIntentResolver（快速路徑）
- **GIVEN** `DeterministicIntentResolver` 配置了 pattern 列表：
  - `{ pattern: /^整理/, intent: { object: "reorganize", confidence: 1.0 } }`
  - `{ pattern: /你好|嗨/, intent: { object: "greeting", confidence: 0.9 } }`
- **WHEN** 輸入 "整理一下" → 回傳 `{ object: "reorganize", confidence: 1.0 }`
- **WHEN** 輸入 "今天天氣如何" → 回傳 `{ object: "unknown", confidence: 0 }`
- **THEN** 匹配到第一個符合的 pattern 就停止（不繼續檢查）
- **THEN** 不匹配任何 pattern 時回傳 `{ object: "unknown", confidence: 0 }`
- **Test**: unit
- **Platform**: js

### AC4: LLMFallbackIntentResolver（兩層意圖解析）
- **GIVEN** `LLMFallbackIntentResolver` 組合 deterministic + LLM fallback
- **WHEN** deterministic resolver 回傳 non-unknown intent
- **THEN** LLM classifier 不被呼叫（省 token）
- **WHEN** deterministic resolver 回傳 unknown
- **THEN** LLM classifier 被呼叫作為 fallback
- **THEN** 結果包含 LLM 分類出的 intent
- **Test**: unit
- **Platform**: js

### AC5: DirectExecutor 快速路徑
- **GIVEN** orchestrator 有 `directExecutors: [myExecutor]`
- **GIVEN** `myExecutor.canHandle(intent)` 回傳 true 當 `intent.object === "task_capture"`
- **WHEN** intent 解析為 `{ object: "task_capture", confidence: 0.95 }`
- **THEN** `myExecutor.execute(input)` 被呼叫
- **THEN** delegate agent 的 `chat()` **不被呼叫**（跳過 LLM）
- **THEN** `result.trace.phaseReached === "direct_execution"`
- **WHEN** `myExecutor.execute()` 回傳 `null`（無法處理）
- **THEN** fallthrough 到 delegate agent
- **Test**: unit
- **Platform**: js

### AC6: PendingState 確認流程
- **GIVEN** orchestrator 有 `pendingStateManager`
- **GIVEN** 上一次 `orchestrator.chat()` 返回了 `pendingConfirmation: { type: "adjust_tags", payload: {...} }`
- **WHEN** `pendingStateManager.getPending(sessionId)` 回傳該 pending state
- **WHEN** 用戶送出新訊息（如 "確認" 或 "取消"）
- **THEN** Phase 0 攔截：不走 intent resolution，直接處理 confirmation
- **THEN** 處理後自動清除 pending state
- **THEN** `result.trace.phaseReached === "pending_confirmation"`
- **Test**: unit
- **Platform**: js

### AC7: PendingState 確認判定（confirm/reject/override）
- **GIVEN** 一個 pending state 存在
- **WHEN** 用戶訊息是確認語氣（"好"、"確認"、"對"、"yes"）→ disposition = "confirm"
- **WHEN** 用戶訊息是否定語氣（"不要"、"取消"、"no"）→ disposition = "reject"
- **WHEN** 用戶訊息是全新指令（與 pending 無關）→ disposition = "override"（清除 pending，走正常流程）
- **THEN** 框架提供 `classifyConfirmationDisposition(message)` 預設實作
- **THEN** 用戶可自訂 `confirmationClassifier` 覆蓋
- **Test**: unit
- **Platform**: js

### AC8: ChannelAdapter 訊息轉換
- **GIVEN** orchestrator 有 `channelAdapter`
- **GIVEN** ChannelAdapter 定義為 `ChannelAdapter<TIn, TOut>`：
  - `parseIncoming(input: TIn): ChannelMessage`
  - `formatOutgoing(result: OrchestrationResult): TOut`
- **WHEN** `orchestrator.processChannel(rawInput)` 被呼叫
- **THEN** `channelAdapter.parseIncoming(rawInput)` 轉換為 `ChannelMessage`
- **THEN** `orchestrator.chat(channelMessage.text, channelMessage.options)` 被呼叫
- **THEN** 結果經過 `channelAdapter.formatOutgoing(result)` 轉換後返回
- **Test**: unit
- **Platform**: js

### AC9: AgentSessionState entity tracking
- **GIVEN** orchestrator 有 `sessionStateStore`
- **WHEN** OrchestrationResult 包含 `presentedEntities`（如列出的任務清單）
- **THEN** entities 被存入 `sessionStateStore` 供下次使用
- **WHEN** 下一次呼叫的 input 包含引用詞（"第一個"、"那個"）
- **THEN** `sessionState.lastPresentedEntities` 可被 DirectExecutor 或 delegate 讀取
- **THEN** session state 透過 `ChatOptions.sessionState` 傳遞給 delegate
- **Test**: unit
- **Platform**: js

### AC10: AgentDecisionTrace 完整性
- **GIVEN** 任何 `orchestrator.chat()` 呼叫
- **THEN** result 的 `trace` 物件包含：
  - `traceId`（唯一 ID）
  - `phaseReached`：`"pending_confirmation" | "direct_execution" | "delegate" | "blocked"`
  - `intentResolved`：解析出的 intent（或 null）
  - `timings`：各階段耗時（ms）
    - `total`、`intentResolution`、`directExecution`、`delegate`
  - `directExecutorUsed`：使用的 executor 名稱（或 null）
  - `delegateUsed`：使用的 delegate 名稱（或 null）
- **Test**: unit
- **Platform**: js

### AC11: Generic intent types + TypeScript generics
- **GIVEN** 框架匯出 `GenericIntentObject = "greeting" | "query" | "action" | "confirmation" | "unknown"`
- **WHEN** 用戶定義自訂 intent type：`type MyIntent = GenericIntentObject | "task_capture" | "calendar_query"`
- **THEN** `DeterministicIntentResolver<MyIntent>` 可正確型別化 pattern 中的 intent.object
- **THEN** `AgentOrchestrator<MyIntent>` 的 result.intent 型別自動推導為 `IntentResult<MyIntent>`
- **THEN** delegate map key 也限制為 `MyIntent` 型別
- **Test**: unit (TypeScript 編譯驗證)
- **Platform**: js

### AC12: Intent-to-delegate routing（多 agent）
- **GIVEN** orchestrator 配置 `delegates: Map<string, AgentChatDelegate>`
  - `"task_capture" → taskAgent`
  - `"calendar_query" → calendarAgent`
- **GIVEN** `delegate`（default）設定為 generalAgent
- **WHEN** intent 解析為 `{ object: "task_capture" }`
- **THEN** `taskAgent.chat()` 被呼叫（不是 generalAgent）
- **WHEN** intent 為 `"unknown"` 或不在 delegates map 中
- **THEN** 默認 `delegate`（generalAgent）被呼叫
- **THEN** `result.trace.delegateUsed` 記錄實際使用的 delegate 名稱
- **Test**: unit
- **Platform**: js

### AC13: Lifecycle hooks
- **GIVEN** orchestrator 配置 `lifecycleHooks: { beforeMessage, afterMessage, onError }`
- **WHEN** `orchestrator.chat()` 被呼叫
- **THEN** `beforeMessage(message, options)` 在任何處理前被呼叫
- **THEN** `afterMessage(result)` 在返回結果前被呼叫
- **WHEN** 任何階段拋出異常
- **THEN** `onError(error)` 被呼叫
- **THEN** hooks 的錯誤不影響主流程（catch + log，不 rethrow）
- **Test**: unit
- **Platform**: js

### AC14: OrchestrationResult 向後相容 NaruResult
- **GIVEN** `OrchestrationResult` extends `NaruResult` 的所有欄位（content, blocked, usage, toolCalls）
- **GIVEN** 新增欄位：`intent`, `trace`, `pendingConfirmation`, `sessionId`
- **WHEN** 用戶只用 NaruResult 的欄位
- **THEN** 不需要改任何既有程式碼
- **THEN** 新欄位全部 optional 或有合理 default（intent: null, trace: always present）
- **Test**: unit (型別驗證)
- **Platform**: js

---

## Test Strategy

| AC | Type | Location | Platform |
|----|------|----------|----------|
| AC1 | unit | js/tests/orchestration/delegate.test.ts | js |
| AC2 | unit | js/tests/orchestration/orchestrator.test.ts | js |
| AC3 | unit | js/tests/orchestration/intent.test.ts | js |
| AC4 | unit | js/tests/orchestration/intent.test.ts | js |
| AC5 | unit | js/tests/orchestration/executor.test.ts | js |
| AC6 | unit | js/tests/orchestration/pending.test.ts | js |
| AC7 | unit | js/tests/orchestration/pending.test.ts | js |
| AC8 | unit | js/tests/orchestration/channel.test.ts | js |
| AC9 | unit | js/tests/orchestration/session-state.test.ts | js |
| AC10 | unit | js/tests/orchestration/orchestrator.test.ts | js |
| AC11 | unit | js/tests/orchestration/types.test.ts | js |
| AC12 | unit | js/tests/orchestration/orchestrator.test.ts | js |
| AC13 | unit | js/tests/orchestration/lifecycle.test.ts | js |
| AC14 | unit | js/tests/orchestration/result.test.ts | js |

---

## Out of Scope
- **Python 版本** — 這次只做 JS，Python 後續跟進
- **NaruAgent 內部修改** — NaruAgent API 不變，不重構其內部
- **具體 channel 實作** — 只提供 `ChannelAdapter` 介面和 `processChannel()` 方法，不實作 LINE/Slack adapter（留給應用層）
- **具體 intent 實作** — 只提供框架類別和 generic intent types，不實作 Naruvia 的 task_capture 等具體 intents
- **Agent handoff (response-level)** — 本次不支援 agent 在回覆中觸發 handoff（agent A 回覆中說 "transfer to agent B"）。只支援 intent-level routing。如需 handoff，Phase 2 再做。
- **Streaming** — AgentOrchestrator 目前不暴露 streaming（同 Naruvia 設計）。NaruAgent 原生 streaming 不受影響。

---

## Files Expected to Create
- `js/src/orchestration/orchestrator.ts` — AgentOrchestrator 主類
- `js/src/orchestration/intent.ts` — IntentResolver 相關類別
- `js/src/orchestration/executor.ts` — BaseDirectExecutor 介面
- `js/src/orchestration/channel.ts` — ChannelAdapter 介面
- `js/src/orchestration/pending.ts` — PendingStateManager + InMemory 實作
- `js/src/orchestration/session-state.ts` — SessionState 相關
- `js/src/orchestration/trace.ts` — AgentDecisionTrace 型別
- `js/src/orchestration/result.ts` — OrchestrationResult 型別
- `js/src/orchestration/index.ts` — barrel export
- `js/tests/orchestration/*.test.ts` — 測試檔案

## Files Expected to Modify
- `js/src/index.ts` — 新增 orchestration module re-export
- `js/src/types.ts` — 新增 `AgentChatDelegate` 介面（如尚未存在）

## Files That Must NOT Change
- `js/src/agent.ts` — NaruAgent 內部不改（它已自然滿足 AgentChatDelegate）
- `js/src/tools/base.ts` — 不改
- `js/src/skills/*.ts` — 不改

---

## PAUSE Gates
- [ ] DB migration: no
- [ ] Test data deletion: no
- [ ] Deployment: no（library，不需 deploy）

---

## Design Notes

### 4-Phase Routing（核心演算法）

```
chat(message, options)
  │
  ├─ Phase 0: Pending Confirmation
  │   pendingStateManager.getPending(sessionId)
  │   若有 → classifyDisposition → confirm/reject/override
  │   confirm → 執行 pending action → return
  │   reject → 清除 pending → return rejection message
  │   override → 清除 pending → 繼續 Phase 1
  │
  ├─ Phase 1: Intent Resolution
  │   intentResolver.resolve({ message, history, sessionState })
  │   若無 resolver → skip（intent = null）
  │
  ├─ Phase 2: Direct Execution
  │   for (executor of directExecutors):
  │     if executor.canHandle(intent):
  │       result = executor.execute(input)
  │       if result !== null → return
  │   若無 executor 或全部回傳 null → continue
  │
  └─ Phase 3: Delegate
      選擇 delegate:
        delegates.get(intent.object) ?? defaultDelegate
      result = delegate.chat(message, enrichedOptions)
      return OrchestrationResult
```

### TypeScript Generics 設計

```typescript
// 框架提供
type GenericIntentObject = "greeting" | "query" | "action" | "confirmation" | "unknown"

// 用戶擴展
type MyIntent = GenericIntentObject | "task_capture" | "calendar_query" | "reorganize"

// 所有 orchestration 類別泛型化
class AgentOrchestrator<T extends string = GenericIntentObject> { ... }
class DeterministicIntentResolver<T extends string = GenericIntentObject> { ... }
interface BaseDirectExecutor<T extends string = GenericIntentObject> { ... }
interface IntentResult<T extends string = GenericIntentObject> {
  object: T
  confidence: number
  requiresConfirmation?: boolean
}
```

### InMemory 預設實作
所有 store/manager 都提供 InMemory 實作，讓用戶零依賴就能用：
- `InMemoryPendingStateManager` — Map<string, PendingState>
- `InMemorySessionStateStore` — Map<string, AgentSessionState>
