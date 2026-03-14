# Feature: agent-orchestration
# Version: 1.0 — 2026-03-14
# Dev brief: .claude/specs/agent-orchestration/spec.md

Feature: Agent 協作框架
  為了建構具備彈性路由和多 agent 協作的應用程式
  身為使用 naru-agent-js 的開發者
  我希望有一個 orchestration 層能從單一 agent passthrough 擴展到 Swarm 風格的多 agent 路由

  Background:
    Given 一個已配置 model、tools 和 skills 的 NaruAgent 實例

  # ━━━ 第一層：核心 Orchestration ━━━

  @ac1
  Scenario: AgentChatDelegate 介面相容性
    Given NaruAgent 擁有 chat(message, options?) 方法回傳 NaruResult
    When 我將 NaruAgent 作為 delegate 傳給 AgentOrchestrator
    Then TypeScript 編譯無型別錯誤
    And AgentOrchestrator 自身也滿足 AgentChatDelegate
    And 我可以將 orchestrator 巢狀作為其他 orchestrator 的 delegate

  @ac2
  Scenario: 單一 agent 零開銷 passthrough
    Given 一個僅配置 delegate 的 AgentOrchestrator
    And 未設定 intentResolver、directExecutors 或其他選項
    When 我呼叫 orchestrator.chat("Hello")
    Then delegate 的 chat 方法以相同的 message 和 options 被呼叫
    And OrchestrationResult 包含 delegate 的 content、usage 和 toolCalls
    And result.trace.phaseReached 等於 "delegate"
    And result.intent 為 null

  @ac2 @edge-case
  Scenario: Passthrough 完整保留所有 ChatOptions
    Given 一個僅配置 delegate 的 AgentOrchestrator
    When 我呼叫 orchestrator.chat("Hi", { userId: "u1", sessionId: "s1" })
    Then delegate 收到完全相同的 options 物件

  @ac3
  Scenario: 確定性意圖解析器匹配第一個 pattern
    Given 一個 DeterministicIntentResolver 配置了以下 patterns：
      | pattern   | intent_object | confidence |
      | /^整理/    | reorganize    | 1.0        |
      | /你好\|嗨/ | greeting      | 0.9        |
    When 我解析訊息「整理一下任務」
    Then 結果為 { object: "reorganize", confidence: 1.0 }

  @ac3
  Scenario: 確定性意圖解析器無匹配時回傳 unknown
    Given 一個配置了 "reorganize" 和 "greeting" patterns 的 DeterministicIntentResolver
    When 我解析訊息「今天天氣如何」
    Then 結果為 { object: "unknown", confidence: 0 }

  @ac3 @edge-case
  Scenario: 確定性解析器在第一個匹配就停止
    Given 一個 DeterministicIntentResolver 配置了重疊的 patterns：
      | pattern    | intent_object |
      | /你好/      | greeting      |
      | /你好.*嗎/  | question      |
    When 我解析訊息「你好嗎」
    Then 結果匹配 "greeting"（第一個 pattern 優先）

  @ac4
  Scenario: LLM fallback 解析器在確定性匹配時跳過 LLM
    Given 一個組合確定性和 LLM 解析器的 LLMFallbackIntentResolver
    And 確定性解析器對輸入「整理」匹配到 "reorganize"
    When 我解析訊息「整理」
    Then LLM 分類器不會被呼叫
    And 結果為 { object: "reorganize" }

  @ac4
  Scenario: LLM fallback 解析器在確定性回傳 unknown 時呼叫 LLM
    Given 一個組合確定性和 LLM 解析器的 LLMFallbackIntentResolver
    And 確定性解析器對輸入「幫我規劃下週」回傳 "unknown"
    When 我解析訊息「幫我規劃下週」
    Then LLM 分類器作為 fallback 被呼叫
    And 結果包含 LLM 分類出的意圖

  @ac5
  Scenario: DirectExecutor 在高信心度意圖時不走 LLM
    Given 一個配置了 "task_capture" DirectExecutor 的 AgentOrchestrator
    And intentResolver 將「記一下」解析為 { object: "task_capture", confidence: 0.95 }
    When 我呼叫 orchestrator.chat("記一下買牛奶")
    Then DirectExecutor 的 execute 方法被呼叫
    And delegate agent 的 chat 方法不會被呼叫
    And result.trace.phaseReached 等於 "direct_execution"

  @ac5
  Scenario: DirectExecutor 回傳 null 時 fallthrough
    Given 一個配置了 "task_capture" DirectExecutor 的 AgentOrchestrator
    And DirectExecutor 的 execute 方法回傳 null
    When 我呼叫 orchestrator.chat("記一下買牛奶")
    Then delegate agent 的 chat 方法會被呼叫作為 fallback
    And result.trace.phaseReached 等於 "delegate"

  @ac5 @edge-case
  Scenario: 多個 DirectExecutor 按順序嘗試
    Given 一個配置了兩個 DirectExecutors 的 AgentOrchestrator：
      | executor     | handles        |
      | taskExecutor | task_capture   |
      | calExecutor  | calendar_query |
    And 意圖解析為 "task_capture"
    When taskExecutor 回傳 null
    Then calExecutor 不會被嘗試（意圖不符）
    And delegate 處理該訊息

  # ━━━ 第二層：狀態管理 ━━━

  @ac6
  Scenario: Pending state 在意圖解析前攔截
    Given 一個配置了 pendingStateManager 的 AgentOrchestrator
    And session "s1" 存在一個 type 為 "adjust_tags" 的 pending state
    When 我呼叫 orchestrator.chat("確認", { sessionId: "s1" })
    Then Phase 0 攔截該訊息
    And 意圖解析不會執行
    And 處理後 pending state 被清除
    And result.trace.phaseReached 等於 "pending_confirmation"

  @ac6 @edge-case
  Scenario: 無 pending state 時繼續正常流程
    Given 一個配置了 pendingStateManager 的 AgentOrchestrator
    And session "s1" 不存在 pending state
    When 我呼叫 orchestrator.chat("Hello", { sessionId: "s1" })
    Then 正常的意圖解析流程繼續

  @ac7
  Scenario: 確認 disposition 分類使用者肯定回應
    Given 存在一個 pending state
    When 使用者說「好」或「確認」或「yes」
    Then disposition 為 "confirm"

  @ac7
  Scenario: 拒絕 disposition 分類使用者否定回應
    Given 存在一個 pending state
    When 使用者說「不要」或「取消」或「no」
    Then disposition 為 "reject"

  @ac7
  Scenario: 覆蓋 disposition 處理無關訊息
    Given 存在一個 type 為 "adjust_tags" 的 pending state
    When 使用者說「今天天氣如何」（與 pending 動作無關）
    Then disposition 為 "override"
    And pending state 被清除
    And 以新訊息繼續正常流程

  @ac7
  Scenario: 自訂確認分類器覆蓋預設
    Given 一個配置了自訂 confirmationClassifier 的 AgentOrchestrator
    When 使用者送出任何確認訊息
    Then 使用自訂分類器而非預設

  @ac8
  Scenario: Channel adapter 轉換進出訊息
    Given 一個配置了 ChannelAdapter 的 AgentOrchestrator
    When 我呼叫 orchestrator.processChannel(rawChannelInput)
    Then channelAdapter.parseIncoming 將原始輸入轉換為 ChannelMessage
    And 以解析後的訊息呼叫 orchestrator.chat
    And channelAdapter.formatOutgoing 將結果轉換為 channel 格式
    And 回傳格式化後的輸出

  @ac8 @edge-case
  Scenario: 不使用 processChannel 時 channel adapter 不介入
    Given 一個配置了 ChannelAdapter 的 AgentOrchestrator
    When 我直接呼叫 orchestrator.chat（不是 processChannel）
    Then channel adapter 不參與處理
    And orchestrator 正常運作

  @ac9
  Scenario: Session state 儲存已呈現的實體
    Given 一個配置了 sessionStateStore 的 AgentOrchestrator
    When OrchestrationResult 包含 presentedEntities
    Then 實體被存入 session state store
    And 下一次 chat 呼叫可透過 options.sessionState 存取它們

  @ac9 @edge-case
  Scenario: 未配置 store 時的 session state
    Given 一個未配置 sessionStateStore 的 AgentOrchestrator
    When orchestrator.chat 回傳結果
    Then 不嘗試任何 session state 操作
    And 不拋出錯誤

  # ━━━ 第三層：可觀測性 ━━━

  @ac10
  Scenario: 每個結果都包含決策追蹤
    Given 任何 AgentOrchestrator 配置
    When 我以任何訊息呼叫 orchestrator.chat
    Then result.trace 為非 null 的 AgentDecisionTrace
    And trace.traceId 為唯一識別碼
    And trace.phaseReached 為 "pending_confirmation"、"direct_execution"、"delegate" 或 "blocked" 之一
    And trace.timings 至少包含 "total"（毫秒）

  @ac10
  Scenario: 決策追蹤記錄意圖解析耗時
    Given 一個配置了 intentResolver 的 AgentOrchestrator
    When 我呼叫 orchestrator.chat
    Then trace.timings.intentResolution 記錄解析器耗時（毫秒）
    And trace.intentResolved 包含解析出的意圖

  @ac10
  Scenario: 決策追蹤記錄 DirectExecutor 使用情況
    Given 一個由 DirectExecutor 處理訊息的 AgentOrchestrator
    When 我呼叫 orchestrator.chat
    Then trace.directExecutorUsed 包含該 executor 的名稱

  # ━━━ 第四層：型別安全 ━━━

  @ac11
  Scenario: 使用 TypeScript 泛型的通用意圖型別
    Given 框架匯出 GenericIntentObject 型別
    And 開發者定義 MyIntent = GenericIntentObject | "task_capture" | "calendar_query"
    When 建立 DeterministicIntentResolver<MyIntent>
    Then pattern 的 intent.object 值限制為 MyIntent
    And AgentOrchestrator<MyIntent> 的 result.intent 型別為 IntentResult<MyIntent>

  @ac11
  Scenario: 不指定型別參數時使用預設泛型
    Given 開發者建立 DeterministicIntentResolver 未指定型別參數
    Then intent.object 值預設為 GenericIntentObject
    And 不需明確泛型引數即可編譯

  # ━━━ 第五層：多 Agent ━━━

  @ac12
  Scenario: 意圖路由到專職 delegate
    Given 一個配置了以下 delegates 的 AgentOrchestrator：
      | intent_object  | delegate       |
      | task_capture   | taskAgent      |
      | calendar_query | calendarAgent  |
    And 預設 delegate 為 generalAgent
    When 意圖解析為 "task_capture"
    Then taskAgent.chat 被呼叫（不是 generalAgent）
    And result.trace.delegateUsed 等於 "taskAgent"

  @ac12
  Scenario: Unknown 意圖回退到預設 delegate
    Given 一個配置了專職 delegates 和預設 delegate 的 AgentOrchestrator
    When 意圖解析為 "unknown"
    Then 預設 delegate 處理該訊息
    And result.trace.delegateUsed 等於預設 delegate 的名稱

  @ac12 @edge-case
  Scenario: 意圖不在 delegates 映射中時回退到預設
    Given 僅配置了 "task_capture" 和 "calendar_query" 的 delegates
    When 意圖解析為 "greeting"（不在映射中）
    Then 預設 delegate 處理該訊息

  # ━━━ 第六層：生命週期 ━━━

  @ac13
  Scenario: 生命週期 hooks 按順序執行
    Given 一個配置了 beforeMessage 和 afterMessage hooks 的 AgentOrchestrator
    When 我呼叫 orchestrator.chat("Hello")
    Then beforeMessage 在任何處理前被呼叫
    And afterMessage 在結果準備好後被呼叫
    And 結果正常回傳

  @ac13 @edge-case
  Scenario: Hook 錯誤不中斷主流程
    Given 一個配置了會拋出錯誤的 beforeMessage hook 的 AgentOrchestrator
    When 我呼叫 orchestrator.chat("Hello")
    Then 錯誤被捕獲並記錄
    And orchestrator 繼續正常處理
    And 結果成功回傳

  @ac13
  Scenario: onError hook 捕獲處理錯誤
    Given 一個配置了 onError hook 的 AgentOrchestrator
    When delegate 的 chat 方法拋出錯誤
    Then onError 以該錯誤被呼叫
    And 錯誤向呼叫者傳播

  # ━━━ 第七層：結果相容性 ━━━

  @ac14
  Scenario: OrchestrationResult 擴展 NaruResult
    Given orchestrator.chat 回傳的 OrchestrationResult
    Then 包含所有 NaruResult 欄位：content、blocked、usage、toolCalls
    And 額外包含：intent、trace、pendingConfirmation、sessionId
    And 僅讀取 NaruResult 欄位的程式碼無需修改

  @ac14 @edge-case
  Scenario: 新欄位具備安全預設值
    Given 一個最小 orchestrator（僅 delegate）
    When orchestrator.chat 回傳結果
    Then result.intent 為 null
    And result.pendingConfirmation 為 null 或 undefined
    And result.trace 永遠存在（不為 null）
