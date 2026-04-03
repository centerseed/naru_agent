---
type: SPEC
id: SPEC-skill-selector-precision
status: Under Review
ontology_entity: TBD
created: 2026-04-03
updated: 2026-04-03
---

# Feature Spec: Skill Selector 精度提升

## 背景與動機

naru_agent 的 Skill 系統目前提供兩種 selector：KeywordSkillSelector（關鍵字子字串比對）和 EmbeddingSkillSelector（向量相似度）。在實際產品場景（如 zentropy）中，KeywordSkillSelector 因為只做 substring match，無法區分同一關鍵字背後的不同語意意圖，導致頻繁誤觸和漏觸。

典型案例：用戶說「星期三要開會」，意圖是**記錄**這件事到記憶中，但「星期」這個關鍵字 match 到 calendar skill，系統跑去**查行事曆**。同一個表面關鍵字對應完全不同的動作意圖，純關鍵字比對無法區分。

EmbeddingSkillSelector 雖然能做語意相似度，但它只比對「用戶訊息」和「skill 描述」的向量距離，仍然缺乏對**觸發條件**和**排除條件**的精確控制能力。

## 目標用戶

naru_agent SDK 的開發者（使用 Python 或 TypeScript 版本），在定義 skill 時需要精確控制觸發行為。典型場景：5-10 個 skill，彼此有語意重疊，需要根據用戶意圖精準路由。

## 需求

### P0（必須有）

#### 開發者可定義正向觸發條件描述

- **描述**：開發者在定義 skill 時，可以用自然語言描述「什麼情況下應該觸發這個 skill」，而不是只列出關鍵字。
- **Acceptance Criteria**：
  - Given 開發者定義了一個 skill 並設定了自然語言觸發條件（如「用戶想查詢行事曆、問某天有什麼行程」）, When 用戶發送符合該描述的訊息, Then 該 skill 被選中
  - Given 開發者定義了觸發條件, When 用戶發送的訊息不符合描述但包含相同關鍵字（如「星期三要開會」是記錄意圖而非查詢意圖）, Then 該 skill 不被選中

#### 開發者可定義負向排除條件描述

- **描述**：開發者在定義 skill 時，可以用自然語言描述「什麼情況下不應該觸發這個 skill」，明確排除容易誤觸的場景。
- **Acceptance Criteria**：
  - Given 開發者定義了排除條件（如「用戶只是提到日期但意圖是記錄或交辦，不是查行事曆」）, When 用戶發送符合排除條件的訊息, Then 該 skill 不被選中
  - Given 用戶訊息同時符合某 skill 的觸發條件和另一個 skill 的排除條件, Then 兩個判斷各自獨立運作，不互相干擾

#### 新 selector 作為獨立選項，不破壞現有 API

- **描述**：新的語意匹配 selector 是一個新的 `BaseSkillSelector` 實作，開發者可自行選用。現有的 `KeywordSkillSelector` 和 `EmbeddingSkillSelector` 保持不變。
- **Acceptance Criteria**：
  - Given 開發者未指定 selector, When 建構 NaruAgent, Then 預設行為與目前一致（KeywordSkillSelector）
  - Given 開發者選用新的語意 selector, When 建構 NaruAgent, Then skill 選擇使用新的語意匹配邏輯
  - Given 既有使用 KeywordSkillSelector 的程式碼, When 升級 naru_agent 版本, Then 無需修改任何程式碼

### P1（應該有）

#### Python 和 TypeScript 雙版本同步支援

- **描述**：新的 selector 和 skill 定義擴展在 Python 和 TypeScript 版本中同時提供，API 風格一致。
- **Acceptance Criteria**：
  - Given 開發者在 Python 中定義了帶觸發/排除條件的 skill, When 移植到 TypeScript 版本, Then 可以用對等的 API 達成相同效果
  - Given 兩個版本面對相同的 skill 定義和用戶訊息, When 執行選擇, Then 結果一致

#### Skill 定義向下相容

- **描述**：已有的 skill（只有 `triggers` 關鍵字列表、沒有自然語言條件）在新 selector 下仍然能正常運作，觸發/排除條件為可選欄位。
- **Acceptance Criteria**：
  - Given 一個只有 `triggers=["calendar", "行事曆"]` 的舊 skill, When 使用新的語意 selector, Then 這些 triggers 仍被視為觸發依據（向下相容 fallback）

### P2（可以有）

#### 多 selector 組合（Chain / Cascade）

- **描述**：開發者可以組合多個 selector（如先用 keyword 快篩，再用語意 selector 精篩），以在精度和延遲之間取得平衡。
- **Acceptance Criteria**：
  - Given 開發者設定了 keyword → 語意 的兩階段 selector, When 用戶發送訊息, Then 先由 keyword 篩出候選 skill，再由語意 selector 精確判斷

#### Selector 命中理由可觀測

- **描述**：開發者可以在 trace / log 中看到每個 skill 被選中或被排除的理由，用於 debug 和調優。
- **Acceptance Criteria**：
  - Given 啟用了 tracing, When skill 選擇完成, Then trace 中包含每個 skill 的匹配分數或判斷理由

## 明確不包含

- **技術實作選型**：不在本 spec 中決定是用 LLM、embedding、規則引擎或其他方式實現語意匹配——那是 Architect 的決定。
- **Skill 執行邏輯變更**：本 spec 只處理「選哪些 skill」，不改變 skill 被選中後的執行流程。
- **Tool 安全管道**：tool 執行的 pre/post hook 是另一個獨立議題。
- **MCP 整合**：不在本次範圍。

## 技術約束（給 Architect 參考）

- **延遲可接受 200-500ms**：用戶明確表示可接受語意匹配帶來的額外延遲。
- **Skill 規模 5-10 個**：不需要為百級 skill 做極致優化，但設計上不應硬編碼上限。
- **雙語言同步**：Python 和 TypeScript 的 BaseSkillSelector 介面已對齊，新 selector 需兩邊同時實作。
- **現有 selector 不動**：KeywordSkillSelector 和 EmbeddingSkillSelector 保持原樣。

## 開放問題

- BaseSkill 的 `triggers` 欄位是否需要重新命名或標記為 deprecated？還是維持原名，新欄位獨立存在？
