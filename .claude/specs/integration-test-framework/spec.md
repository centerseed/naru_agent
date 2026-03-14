# Plan Brief: integration-test-framework

## Goal
建立跨語言整合測試框架：共用場景資料 + 品質基線，各平台用原生 test runner 執行真實 LLM 測試，覆蓋 tool calling、RAG、skills、orchestration 等所有核心能力。

## BDD Spec
→ 行為契約：`docs/bdd/integration-test-framework.feature`
  場景範圍：@ac1–@ac22（22 個場景）
  其中 @ac11–@ac14 標記為 @js-only（orchestration 目前僅 JS）

## Metadata
- affected: [js]（先做 JS，Python 之後擴展）
- db_migration: false
- deploy_required: false

## 架構設計

### 目錄結構

```
tests/shared/                              # ← 新增：跨語言共用資料
├── baselines/
│   └── quality_baseline.json              # 統一品質閾值（合併現有兩份）
├── scenarios/
│   ├── tool-calling.json                  # 工具呼叫測試場景
│   ├── rag.json                           # RAG 測試場景 + 知識文本
│   ├── skills.json                        # Skill 測試場景
│   ├── quality.json                       # 品質、token、併發場景
│   └── memory-compression.json            # 記憶、壓縮場景
└── knowledge/
    ├── facts.json                         # 向量知識測試文本（現有 7 條）
    └── graph-text.json                    # 知識圖譜測試文本

js/tests/integration/                      # ← 重構：改讀共用場景
├── baselines/                             # 刪除（移到 tests/shared/）
├── helpers.ts                             # 保留，改讀 shared scenarios
├── test_tool_calling.test.ts              # @ac3–@ac5（從 quality_baseline 拆出）
├── test_rag.test.ts                       # @ac6–@ac7（從 capability_baseline 拆出）
├── test_skills.test.ts                    # @ac8–@ac10（新增）
├── test_orchestration.test.ts             # @ac11–@ac14（新增）
├── test_quality.test.ts                   # @ac15–@ac18（從 quality_baseline 拆出）
├── test_memory.test.ts                    # @ac19（從 capability_baseline 拆出）
├── test_compression.test.ts               # @ac20（從 capability_baseline 拆出）
├── test_guardrails.test.ts                # @ac21（新增）
└── test_streaming.test.ts                 # @ac22（新增）
```

### 共用場景格式

每個場景 JSON 定義測試輸入和預期行為，runner 讀取後轉為原生測試：

```json
// tests/shared/scenarios/tool-calling.json
{
  "scenarios": [
    {
      "id": "single_tool_selection",
      "ac": "ac3",
      "description": "單一工具選擇",
      "input": "請幫我計算寄到台北的運費，包裹重量 2 公斤",
      "expect": {
        "blocked": false,
        "toolCalls_contains": ["calculate_shipping_cost"],
        "content_not_empty": true
      }
    },
    {
      "id": "chitchat_no_tools",
      "ac": "ac3",
      "tags": ["edge-case"],
      "description": "閒聊不觸發工具",
      "input": "你好，今天天氣真好",
      "expect": {
        "blocked": false,
        "toolCalls_max_count": 0,
        "content_not_empty": true
      }
    },
    {
      "id": "multi_tool_chaining",
      "ac": "ac4",
      "description": "多工具鏈式呼叫",
      "input": "幫我搜尋無線耳機，然後查看第一個產品的詳情和庫存",
      "expect": {
        "blocked": false,
        "toolCalls_contains": ["search_products"],
        "toolCalls_contains_any": ["get_product_detail", "check_inventory"],
        "content_not_empty": true
      }
    }
  ]
}
```

```json
// tests/shared/scenarios/skills.json
{
  "skills_definition": {
    "weather_skill": {
      "name": "weather",
      "description": "天氣查詢技能",
      "triggers": ["天氣", "氣溫", "下雨"],
      "promptInjection": "你現在具備天氣查詢能力。回答天氣問題時，使用 get_weather 工具。",
      "extraTools": [
        {
          "name": "get_weather",
          "description": "查詢指定城市天氣",
          "parameters": { "city": "string" },
          "mockReturn": "{\"city\":\"台北\",\"temp\":\"22°C\",\"condition\":\"晴天\"}"
        }
      ]
    },
    "greeting_skill": {
      "name": "greeting",
      "description": "問候技能",
      "triggers": [],
      "alwaysActive": true,
      "promptInjection": "每次回覆開頭加上友善的問候語。"
    }
  },
  "scenarios": [
    {
      "id": "keyword_trigger",
      "ac": "ac8",
      "description": "關鍵字觸發 Skill",
      "skill": "weather_skill",
      "input": "台北今天天氣如何？",
      "expect": {
        "toolCalls_contains": ["get_weather"],
        "content_not_empty": true
      }
    },
    {
      "id": "no_trigger",
      "ac": "ac8",
      "tags": ["edge-case"],
      "description": "無觸發詞不啟動 Skill",
      "skill": "weather_skill",
      "input": "你好，我想問一個問題",
      "expect": {
        "toolCalls_not_contains": ["get_weather"]
      }
    },
    {
      "id": "skill_injects_tool",
      "ac": "ac9",
      "description": "Skill 注入額外工具",
      "skill": "weather_skill",
      "input": "查一下高雄的天氣",
      "expect": {
        "toolCalls_contains": ["get_weather"],
        "content_keywords_any": ["高雄"]
      }
    },
    {
      "id": "always_active",
      "ac": "ac10",
      "description": "Always-active Skill",
      "skill": "greeting_skill",
      "input": "1+1等於多少？",
      "expect": {
        "content_not_empty": true
      }
    }
  ]
}
```

### 斷言語法（assertion DSL）

Runner 需要支援以下斷言類型：

| 斷言 | 說明 |
|------|------|
| `blocked` | result.blocked === value |
| `content_not_empty` | result.content.length > 0 |
| `content_keywords_any` | content 包含至少一個關鍵字 |
| `content_keywords_all` | content 包含所有關鍵字 |
| `toolCalls_contains` | toolCalls 包含所有指定工具 |
| `toolCalls_contains_any` | toolCalls 包含至少一個指定工具 |
| `toolCalls_not_contains` | toolCalls 不包含指定工具 |
| `toolCalls_max_count` | toolCalls.length <= value |
| `toolCalls_min_count` | toolCalls.length >= value |
| `tokens_max` | usage.totalTokens <= value（從 baseline 讀） |
| `trace_min_spans` | trace spans 數量 >= value |
| `has_stream_events` | streaming 事件包含指定類型 |

### Runner 實作（JS）

```typescript
// js/tests/integration/helpers.ts 擴展

import scenarios from "../../../tests/shared/scenarios/tool-calling.json";

interface ScenarioExpect {
  blocked?: boolean;
  content_not_empty?: boolean;
  content_keywords_any?: string[];
  content_keywords_all?: string[];
  toolCalls_contains?: string[];
  toolCalls_contains_any?: string[];
  toolCalls_not_contains?: string[];
  toolCalls_max_count?: number;
  toolCalls_min_count?: number;
}

function assertResult(result: NaruResult, expect: ScenarioExpect) {
  if (expect.blocked !== undefined) expect(result.blocked).toBe(expect.blocked);
  if (expect.content_not_empty) expect(result.content.length).toBeGreaterThan(0);
  if (expect.toolCalls_contains) {
    for (const tool of expect.toolCalls_contains) {
      expect(result.toolCalls).toContain(tool);
    }
  }
  // ... 其他斷言
}
```

### 工具定義

現有 16 個電商工具保留在各平台的 helpers 中（Python 和 JS 的工具實作不同，但名稱、參數、行為一致）。共用資料只定義場景，不定義工具實作。

Skill 測試的工具定義在場景 JSON 中描述（name, description, parameters, mockReturn），由 runner 動態建立。

## AC → Test Mapping

| AC | 場景 | 測試檔案 | 平台 |
|----|------|----------|------|
| @ac1 | 共用場景定義 | helpers.ts（載入驗證） | js |
| @ac2 | 共用品質基線 | helpers.ts（載入驗證） | js |
| @ac3 | 單工具選擇 + 閒聊不觸發 | test_tool_calling.test.ts | js |
| @ac4 | 多工具鏈式呼叫 | test_tool_calling.test.ts | js |
| @ac5 | 並行工具執行 | test_tool_calling.test.ts | js |
| @ac6 | 向量知識檢索 | test_rag.test.ts | js |
| @ac7 | 知識圖譜查詢 | test_rag.test.ts | js |
| @ac8 | 關鍵字觸發 + 無觸發 | test_skills.test.ts | js |
| @ac9 | Skill 注入工具 | test_skills.test.ts | js |
| @ac10 | Always-active Skill | test_skills.test.ts | js |
| @ac11 | 單一 agent passthrough | test_orchestration.test.ts | js |
| @ac12 | Intent 路由 | test_orchestration.test.ts | js |
| @ac13 | Direct executor | test_orchestration.test.ts | js |
| @ac14 | 多步驟確認 | test_orchestration.test.ts | js |
| @ac15 | Token 使用量 | test_quality.test.ts | js |
| @ac16 | 並行使用者隔離 | test_quality.test.ts | js |
| @ac17 | 回應品質 | test_quality.test.ts | js |
| @ac18 | Trace 完整性 | test_quality.test.ts | js |
| @ac19 | 記憶萃取 | test_memory.test.ts | js |
| @ac20 | 長對話壓縮 | test_compression.test.ts | js |
| @ac21 | 輸入防護 | test_guardrails.test.ts | js |
| @ac22 | 串流事件 | test_streaming.test.ts | js |

## Implementation Notes

### 參考實作
- 現有 `js/tests/integration/test_quality_baseline.test.ts` — 測試結構和工具定義
- 現有 `js/tests/integration/test_capability_baseline.test.ts` — RAG 和 knowledge graph 測試
- 現有 `js/tests/integration/helpers.ts` — makeAgent、tool 定義、callLog 追蹤

### 重構策略
1. **抽取共用資料** — 將現有 helpers.ts 中的 `KNOWLEDGE_FACTS`、`GRAPH_TEXT`、baseline JSON 搬到 `tests/shared/`
2. **拆分測試檔案** — 將現有兩個大測試檔拆成按能力分類的小檔案
3. **新增 skill + orchestration 測試** — 這是全新的覆蓋範圍
4. **建立 assertion helper** — `assertScenarioResult()` 統一斷言邏輯
5. **向後相容** — `npm run test:integration` 仍然跑所有 integration tests

### Model 配置
- 預設模型：`gemini-2.5-flash-lite`（透過 `CHAT_AGENT_MODEL` 環境變數覆蓋）
- Summary 模型：`gemma-3-12b-it`（透過 `SUMMARY_MODEL` 環境變數覆蓋）
- Embedding：`gemini-embedding-001`
- API Key：`GOOGLE_GENERATIVE_AI_API_KEY`

### 跳過策略
- 無 API key → 全部 skip（現有 `describeIf` 模式）
- `@js-only` 場景 → Python runner 自動跳過

## Files to Change

### 新增
- `tests/shared/baselines/quality_baseline.json` — 合併的品質基線
- `tests/shared/scenarios/tool-calling.json` — 工具呼叫場景
- `tests/shared/scenarios/rag.json` — RAG + 知識圖譜場景及測試文本
- `tests/shared/scenarios/skills.json` — Skill 場景及 skill 定義
- `tests/shared/scenarios/orchestration.json` — Orchestration 場景（JS only）
- `tests/shared/scenarios/quality.json` — 品質、token、併發、trace 場景
- `tests/shared/scenarios/memory-compression.json` — 記憶、壓縮場景
- `tests/shared/scenarios/guardrails.json` — 防護場景
- `tests/shared/scenarios/streaming.json` — 串流場景
- `tests/shared/knowledge/facts.json` — 向量知識測試文本
- `tests/shared/knowledge/graph-text.json` — 知識圖譜測試文本
- `js/tests/integration/test_tool_calling.test.ts` — @ac3–@ac5
- `js/tests/integration/test_rag.test.ts` — @ac6–@ac7
- `js/tests/integration/test_skills.test.ts` — @ac8–@ac10
- `js/tests/integration/test_orchestration.test.ts` — @ac11–@ac14
- `js/tests/integration/test_quality.test.ts` — @ac15–@ac18
- `js/tests/integration/test_memory.test.ts` — @ac19
- `js/tests/integration/test_compression.test.ts` — @ac20
- `js/tests/integration/test_guardrails.test.ts` — @ac21
- `js/tests/integration/test_streaming.test.ts` — @ac22
- `js/tests/integration/scenario-runner.ts` — 共用斷言 helper

### 修改
- `js/tests/integration/helpers.ts` — 改讀 `tests/shared/` 的資料
- `js/vitest.integration.config.ts` — 確認 include pattern 涵蓋新檔案

### 刪除
- `js/tests/integration/test_quality_baseline.test.ts` — 拆分到新檔案後刪除
- `js/tests/integration/test_capability_baseline.test.ts` — 拆分到新檔案後刪除
- `js/tests/integration/baselines/quality_baseline.json` — 移到 tests/shared/
- `tests/integration/baselines/quality_baseline.json` — 移到 tests/shared/（Python 之後指向同一份）

## Files That Must NOT Change
- `js/src/agent.ts` — 測試框架不改 production code
- `js/src/orchestration/*.ts` — 不改 production code
- `js/src/skills/*.ts` — 不改 production code
- `js/tests/orchestration/*.test.ts` — 現有 unit tests 不動

## Out of Scope
- Python runner（之後擴展）
- E2E 測試（跨服務整合）
- Performance benchmark（非 regression 測試）
- CI/CD pipeline 設定

## PAUSE Gates
- [ ] DB migration: no
- [ ] Test data deletion: no
- [ ] Deployment: no
