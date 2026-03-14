# Feature: integration-test-framework
# Version: 1.0 — 2026-03-14
# Dev brief: .claude/specs/integration-test-framework/plan.md

Feature: 跨語言整合測試框架
  In order to 確保 Python 和 TypeScript 雙版本行為一致
  As a 框架開發者
  I want to 用共用場景資料對兩個平台執行同一組真實 LLM 測試

  # ━━━ 共用場景資料 ━━━

  @ac1
  Scenario: 共用測試場景定義
    Given 測試場景定義檔存放在 tests/shared/scenarios/
    When Python runner 或 JS runner 讀取場景定義
    Then 兩個平台使用相同的測試資料、預期結果、和品質閾值

  @ac2
  Scenario: 共用品質基線
    Given tests/shared/baselines/quality_baseline.json 定義品質閾值
    When 整合測試執行完成
    Then 結果與基線比較，超出閾值即失敗

  # ━━━ Tool Calling ━━━

  @ac3
  Scenario: 單一工具選擇
    Given agent 載入 16 個電商工具
    When 使用者詢問需要特定工具的問題
    Then agent 選擇正確的工具並回傳結果

  @ac3 @edge-case
  Scenario: 閒聊不觸發工具
    Given agent 載入 16 個電商工具
    When 使用者傳送閒聊訊息
    Then agent 不呼叫任何工具

  @ac4
  Scenario: 多工具鏈式呼叫
    Given agent 載入 16 個電商工具
    When 使用者的需求需要多個工具協作
    Then agent 依序呼叫必要的工具並整合結果

  @ac5
  Scenario: 並行工具執行
    Given agent 載入多個互不依賴的工具
    When 使用者的需求可並行處理
    Then 工具呼叫在合理時間內完成

  # ━━━ RAG / Knowledge ━━━

  @ac6
  Scenario: 向量知識檢索
    Given knowledge store 已載入測試知識文件
    When 使用者詢問知識庫中的資訊
    Then agent 回應包含正確的知識內容

  @ac7
  Scenario: 知識圖譜查詢
    Given graph knowledge store 已載入實體關係資料
    When 使用者詢問需要推理的問題
    Then 回應包含圖譜推導的關聯資訊

  # ━━━ Skills ━━━

  @ac8
  Scenario: 關鍵字觸發 Skill
    Given agent 註冊了帶有觸發詞的 skill
    When 使用者訊息包含觸發詞
    Then skill 的 prompt injection 影響 LLM 回應行為

  @ac8 @edge-case
  Scenario: 無觸發詞不啟動 Skill
    Given agent 註冊了帶有觸發詞的 skill
    When 使用者訊息不包含任何觸發詞
    Then skill 不被啟動，agent 以預設行為回應

  @ac9
  Scenario: Skill 注入額外工具
    Given agent 註冊了會注入額外工具的 skill
    When 使用者訊息觸發該 skill
    Then 注入的工具可被 LLM 呼叫

  @ac10
  Scenario: Always-active Skill
    Given agent 註冊了 alwaysActive 的 skill
    When 使用者傳送任意訊息
    Then 該 skill 永遠被執行

  # ━━━ Orchestration（JS only）━━━

  @ac11 @js-only
  Scenario: 單一 agent passthrough
    Given orchestrator 只配置一個 delegate agent
    When 使用者傳送訊息
    Then 訊息直接轉發給 delegate 處理

  @ac12 @js-only
  Scenario: Intent 路由到專屬 agent
    Given orchestrator 配置了多個 delegate 和 intent resolver
    When 使用者訊息匹配特定 intent pattern
    Then 訊息路由到對應的 delegate agent

  @ac13 @js-only
  Scenario: Direct executor 快速路徑
    Given orchestrator 配置了 direct executor
    When 使用者訊息觸發高信心度操作
    Then 跳過 LLM 直接執行並回傳結果

  @ac14 @js-only
  Scenario: 多步驟確認流程
    Given orchestrator 配置了 pending state manager
    When 使用者需要確認操作
    Then orchestrator 管理確認狀態並在確認後執行

  # ━━━ 品質與效能 ━━━

  @ac15
  Scenario: Token 使用量控制
    Given 品質基線定義了 token 上限
    When agent 處理簡單聊天和工具呼叫
    Then token 使用量不超過基線閾值

  @ac16
  Scenario: 並行使用者隔離
    Given 多個使用者同時使用 agent
    When 三個使用者並行發送不同請求
    Then 每個使用者收到正確的回應，互不干擾

  @ac17
  Scenario: 回應品質驗證
    Given agent 配置了語言指令
    When 使用者以中文提問
    Then 回應遵從語言指令且不幻覺不存在的工具

  @ac18
  Scenario: Trace 完整性
    Given agent 啟用 tracing
    When agent 處理包含工具呼叫的請求
    Then trace 包含完整的 span 資訊和時間戳

  # ━━━ Memory ━━━

  @ac19
  Scenario: 記憶萃取與檢索
    Given agent 配置了 memory manager
    When 使用者在對話中提供個人偏好
    Then 後續對話 agent 能回憶該偏好

  # ━━━ Context Compression ━━━

  @ac20
  Scenario: 長對話壓縮
    Given agent 啟用 context compression
    When 對話超過壓縮閾值
    Then 壓縮後保留率超過基線閾值

  # ━━━ Guardrails ━━━

  @ac21
  Scenario: 輸入防護
    Given agent 配置了關鍵字防護
    When 使用者輸入包含禁止詞彙
    Then 訊息被攔截，不送往 LLM

  # ━━━ Streaming ━━━

  @ac22
  Scenario: 串流事件序列
    Given agent 支援 streaming 模式
    When 使用者發送訊息並以串流接收
    Then 事件依序包含 text-start、text-delta、text-end
