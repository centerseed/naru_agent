# naru_agent

輕量、可組合的 Agent 協作框架。從單一 agent 到多 agent 路由，同一個框架涵蓋。

支援 Python 和 TypeScript 雙版本，設計為 SDK 嵌入各專案使用。

## 定位

```
最小配置                              最大配置（Swarm-like）
──────────────────────────────────────────────────────────
NaruAgent.chat("Hello")              AgentOrchestrator
  （單一 agent，零開銷）                ├─ intentResolver（快速路徑 + LLM fallback）
                                      ├─ directExecutors[]（跳過 LLM 的快速路徑）
                                      ├─ delegates Map（intent → 專屬 agent）
                                      │   ├─ AgentPipeline（串接處理）
                                      │   ├─ AgentFanout（並行派工 + 合併）
                                      │   └─ AgentHandoffLoop（agent 間轉接）
                                      ├─ pendingStateManager（多步驟確認）
                                      ├─ sessionStateStore（實體追蹤）
                                      └─ channelAdapter（LINE/Slack/API）
```

## 雙版本

| | Python | TypeScript |
|---|--------|-----------|
| LLM 驅動 | Agno + LiteLLM（100+ models） | Vercel AI SDK（100+ models） |
| Tool 定義 | Pydantic / `@tool` decorator | Zod / `BaseTool` class |
| 安裝 | `pip install -e .` | `npm install naru-agent-js` |

---

## 架構總覽

```
┌─────────────────────────────────────────────────────────┐
│ AgentOrchestrator（可選的協作層）                         │
│                                                         │
│ Phase 0: Pending Confirmation（多步驟確認攔截）           │
│ Phase 1: Intent Resolution（快速路徑 + LLM fallback）    │
│ Phase 2: Direct Execution（高信心度操作，跳過 LLM）      │
│ Phase 3: Delegate（路由到對應的 NaruAgent）               │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────┐
│ NaruAgent（核心 agent，可獨立使用）                       │
│                                                         │
│ ┌──────────┐ ┌────────┐ ┌───────────┐ ┌──────────────┐  │
│ │ Tools    │ │ Skills │ │ Memory    │ │ Knowledge    │  │
│ │ @tool    │ │ @skill │ │ per-user  │ │ RAG + Graph  │  │
│ └──────────┘ └────────┘ └───────────┘ └──────────────┘  │
│ ┌──────────┐ ┌────────┐ ┌───────────┐ ┌──────────────┐  │
│ │ Session  │ │ Guards │ │ Compress  │ │ Tracing      │  │
│ │ Redis/Mem│ │ I/O    │ │ Context   │ │ JSONL export │  │
│ └──────────┘ └────────┘ └───────────┘ └──────────────┘  │
└─────────────────────────────────────────────────────────┘
```

---

## 快速開始

### Python

```python
from naru_agent import NaruAgent, tool

@tool(description="查詢天氣")
def get_weather(city: str) -> str:
    return f"{city}: 晴天 22°C"

agent = NaruAgent(
    model="gemini/gemini-2.5-flash-lite",
    instructions=["你是一個助手。"],
    tools=[get_weather],
)

result = agent.chat("台北天氣如何？", user_id="user-1")
print(result.content)
```

### TypeScript

```typescript
import { NaruAgent, tool } from "naru-agent-js";
import { anthropic } from "@ai-sdk/anthropic";
import { z } from "zod";

const weatherTool = tool({
  name: "get_weather",
  description: "查詢天氣",
  parameters: z.object({ city: z.string() }),
  execute: async ({ city }) => `${city}: 晴天 22°C`,
});

const agent = new NaruAgent({
  model: anthropic("claude-sonnet-4-5"),
  instructions: ["你是一個助手。"],
  tools: [weatherTool],
});

const result = await agent.chat("台北天氣如何？", "session-1");
```

### Agent Orchestration（Python）

```python
import re
from naru_agent import (
    AgentOrchestrator,
    AgentOrchestratorConfig,
    DeterministicIntentResolver,
    DeterministicPattern,
    OrchestratorIntent,
    InMemoryPendingStateManager,
)

# 單一 agent — 零開銷 passthrough
simple = AgentOrchestrator(AgentOrchestratorConfig(delegate=my_agent))

# 多 agent 路由 — intent 決定哪個 agent 處理
orchestrator = AgentOrchestrator(AgentOrchestratorConfig(
    delegate=general_agent,
    delegates={
        "task_capture": task_agent,
        "calendar_query": cal_agent,
    },
    intent_resolver=DeterministicIntentResolver([
        DeterministicPattern(
            pattern=re.compile(r"記一下|待辦"),
            intent=OrchestratorIntent(object="task_capture", confidence=1.0),
        ),
        DeterministicPattern(
            pattern=re.compile(r"行事曆|會議"),
            intent=OrchestratorIntent(object="calendar_query", confidence=1.0),
        ),
    ]),
    pending_state_manager=InMemoryPendingStateManager(),
))

result = orchestrator.chat("記一下買牛奶", session_id="s1")
# → task_agent 處理，不經過 general_agent
# result.decision_trace.phase_reached == "delegate"
# result.decision_trace.delegate_used == "task_capture"
```

### Composable Primitives（Python）

三個可組合的 primitive，都滿足 `AgentChatDelegate` 介面，可直接當 delegate 插入 orchestrator。

```python
from naru_agent import AgentPipeline, AgentFanout, AgentHandoffLoop

# Sequential Pipeline — A 的輸出自動變 B 的輸入
pipeline = AgentPipeline([
    research_agent,   # 先蒐集資訊
    summary_agent,    # 再摘要
    translate_agent,  # 最後翻譯
])
result = pipeline.chat("量子計算的最新進展")

# Parallel Fan-out — 同時派工給多個 agent，合併結果
fanout = AgentFanout(
    agents=[search_agent, database_agent, api_agent],
    merge=lambda results: NaruResult(
        content="\n".join(r.content for r in results)
    ),
)
result = fanout.chat("找出所有相關資料")

# Agent Handoff — agent 間轉接，max_handoffs 防止無限迴圈
handoff = AgentHandoffLoop(
    agents={"triage": triage_agent, "billing": billing_agent, "tech": tech_agent},
    entry="triage",
    max_handoffs=5,
)
result = handoff.chat("我的帳單有問題")

# 任意組合 — Pipeline 裡放 Fanout，整體當 delegate
orchestrator = AgentOrchestrator(AgentOrchestratorConfig(
    delegate=general_agent,
    delegates={
        "deep_research": AgentPipeline([
            AgentFanout([search_agent, database_agent]),  # 並行蒐集
            summary_agent,                                # 串接摘要
        ]),
    },
    intent_resolver=resolver,
))
```

### Agent Orchestration（TypeScript）

```typescript
import {
  AgentOrchestrator,
  DeterministicIntentResolver,
  InMemoryPendingStateManager,
} from "naru-agent-js";

// 單一 agent — 零開銷 passthrough
const simple = new AgentOrchestrator({ delegate: myAgent });

// 多 agent 路由 — intent 決定哪個 agent 處理
const orchestrator = new AgentOrchestrator({
  delegate: generalAgent,
  delegates: new Map([
    ["task_capture", taskAgent],
    ["calendar_query", calendarAgent],
  ]),
  intentResolver: new DeterministicIntentResolver([
    { pattern: /記一下|待辦/, intent: { object: "task_capture", confidence: 1.0 } },
    { pattern: /行事曆|會議/, intent: { object: "calendar_query", confidence: 1.0 } },
  ]),
  pendingStateManager: new InMemoryPendingStateManager(),
});

const result = await orchestrator.chat("記一下買牛奶", { sessionId: "s1" });
// → taskAgent 處理，不經過 generalAgent
// result.decisionTrace.phaseReached === "delegate"
// result.decisionTrace.delegateUsed === "task_capture"
```

### Composable Primitives（TypeScript）

```typescript
import { AgentPipeline, AgentFanout, AgentHandoffLoop } from "naru-agent-js";

// Sequential Pipeline
const pipeline = new AgentPipeline([researchAgent, summaryAgent, translateAgent]);

// Parallel Fan-out
const fanout = new AgentFanout([searchAgent, dbAgent, apiAgent], {
  merge: (results) => ({ ...results[0], content: results.map(r => r.content).join("\n") }),
});

// Agent Handoff
const handoff = new AgentHandoffLoop(
  new Map([["triage", triageAgent], ["billing", billingAgent], ["tech", techAgent]]),
  "triage",
);

// 任意組合 — 都滿足 AgentChatDelegate，可直接當 delegate
const orchestrator = new AgentOrchestrator({
  delegate: generalAgent,
  delegates: new Map([
    ["deep_research", new AgentPipeline([
      new AgentFanout([searchAgent, dbAgent]),
      summaryAgent,
    ])],
  ]),
  intentResolver: resolver,
});
```

---

## 核心模組

### NaruAgent

框架的核心 agent，可獨立使用或作為 `AgentOrchestrator` 的 delegate。

- **Tools** — `@tool` decorator / `BaseTool` class，sync/async 皆可，多 tool calls 自動並行；`max_parallel_tools` / `maxParallelTools` 可限制同時執行數量；`NaruToolkit` 內建 per-turn call deduplication（`deduplicate_calls=True`），防止 LLM 在同一輪 ReAct loop 重複呼叫相同工具（TOOL_STORM）
- **Skills** — 根據觸發詞動態注入 prompt 和額外 tools，`KeywordSkillSelector` / `EmbeddingSkillSelector`
- **Memory** — LLM 驅動的事實萃取與和解，per-user scope。本地：`MemoryManager` + ChromaDB；生產：`Mem0MemoryManager` + pgvector（三層記憶）
- **Knowledge（RAG）** — `ChromaKnowledgeStore`（向量搜索 + Contextual Retrieval）、`GraphKnowledgeStore`（知識圖譜）、`HybridKnowledgeStore`（混合）
- **Session** — `InMemorySessionStore`（開發）/ `RedisSessionStore`（生產），stateless 多 instance 部署
- **Guardrails** — 輸入/輸出雙層防護，`KeywordGuardrail` + 自訂 LLM 護欄
- **Context Compression** — 長對話自動背景壓縮，避免 context window 超載
- **Intent Classification** — 快速分類意圖，跳過不必要的 RAG/tool calls
- **Tool Selection** — embedding 相似度篩選 top-k 工具，節省 tokens
- **Tracing** — 完整執行鏈路記錄 + JSONL 導出
- **Streaming** — async generator yield `StreamEvent`

### AgentOrchestrator（Python + JS）

可選的協作層，將多個 NaruAgent 組合為路由系統。Python 和 TypeScript 雙版本已完成。

**4 階段路由：**

| Phase | 名稱 | 說明 |
|-------|------|------|
| 0 | Pending Confirmation | 多步驟確認攔截（confirm/reject/override） |
| 1 | Intent Resolution | 快速路徑（keyword/regex）+ LLM fallback |
| 2 | Direct Execution | 高信心度操作，跳過 LLM |
| 3 | Delegate | 路由到對應的 NaruAgent（或 default） |

**核心元件：**

| 元件 | 用途 |
|------|------|
| `DeterministicIntentResolver` | keyword/regex 意圖解析（零 LLM 成本） |
| `LLMFallbackIntentResolver` | 組合 deterministic + LLM 分類器 |
| `BaseDirectExecutor` | 高信心度操作的快速路徑介面 |
| `ChannelAdapter<TIn, TOut>` | channel 抽象（LINE/Slack/API） |
| `InMemoryPendingStateManager` | 多步驟確認狀態管理 |
| `InMemorySessionStateStore` | 實體追蹤（指代消解） |

**Composable Primitives：**

三個獨立的組合元件，都滿足 `AgentChatDelegate` 介面，可作為 delegate 插入 orchestrator 或巢狀組合。

| 元件 | 用途 |
|------|------|
| `AgentPipeline` | 串接多個 agent — A 的輸出自動變 B 的輸入 |
| `AgentFanout` | 並行派工給多個 agent，合併結果（Python 用 ThreadPoolExecutor，JS 用 Promise.all） |
| `AgentHandoffLoop` | agent 間轉接鏈，`max_handoffs` 防止無限迴圈，透過 `NaruResult.handoff` 觸發 |

**泛型支援：**

```python
# Python — TypeVar + Generic
from naru_agent import AgentOrchestrator, AgentOrchestratorConfig, DeterministicIntentResolver

MyIntent = str  # "task_capture" | "calendar_query" | ...
orchestrator: AgentOrchestrator[MyIntent] = AgentOrchestrator(AgentOrchestratorConfig(...))
```

```typescript
// TypeScript — Generics
type MyIntent = GenericIntentObject | "task_capture" | "calendar_query";
const orchestrator = new AgentOrchestrator<MyIntent>({ ... });
// result.orchestrationIntent?.object 型別為 MyIntent
```

---

## 安裝

### Python

```bash
# 作為 git submodule
git submodule add <repo_url> naru_agent
pip install -e naru_agent

# 可選依賴
pip install -e "naru_agent[chromadb]"      # ChromaDB RAG
pip install -e "naru_agent[graph]"         # 知識圖譜
pip install -e "naru_agent[mem0]"          # Mem0 生產記憶
pip install -e "naru_agent[redis]"         # Redis session/compression
pip install -e "naru_agent[embeddings]"    # sentence-transformers
```

### TypeScript

```bash
npm install naru-agent-js
# peer deps（選擇 LLM provider）
npm install @ai-sdk/anthropic  # 或 @ai-sdk/google, @ai-sdk/openai
```

---

## Python 目錄結構

```
naru_agent/
├── agent.py                    # NaruAgent 核心
├── runner.py                   # ReAct 執行引擎（sync + async streaming）
├── streaming.py                # StreamEvent 類型
├── events.py                   # 輕量事件匯流排
├── llm/                        # LLM 抽象 + LiteLLM 實作
├── tools/                      # BaseTool + @tool + 內建 RAG 工具
├── skills/                     # BaseSkill + @skill + SkillRegistry + Selectors
├── memory/                     # MemoryStore + MemoryManager + Mem0
├── knowledge/                  # BaseKnowledgeStore + Chroma + Graph + Hybrid
├── session/                    # BaseSessionStore + InMemory + Redis
├── guardrails/                 # BaseGuardrail + KeywordGuardrail
├── intent/                     # BaseIntentClassifier + LLM + ToolCalling
├── tool_selection/             # BaseToolSelector + Embedding
├── compression/                # ContextCompressor + SummaryStore
├── tracing/                    # Trace + Span + Collector + JSONL Exporter
└── orchestration/              # AgentOrchestrator（4-phase routing）
    ├── orchestrator.py         #   主類 + AgentChatDelegate Protocol
    ├── intent.py               #   Deterministic + LLMFallback
    ├── executor.py             #   BaseDirectExecutor
    ├── pipeline.py             #   AgentPipeline（串接處理）
    ├── fanout.py               #   AgentFanout（並行派工）
    ├── handoff.py              #   AgentHandoffLoop（agent 轉接）
    ├── channel.py              #   ChannelAdapter
    ├── pending.py              #   PendingStateManager
    ├── session_state.py        #   AgentSessionState
    ├── trace.py                #   AgentDecisionTrace
    └── result.py               #   OrchestrationResult
```

## TypeScript 目錄結構

```
js/src/
├── agent.ts                    # NaruAgent 核心（Vercel AI SDK）
├── types.ts                    # 共用型別
├── tools/                      # BaseTool + tool() factory
├── skills/                     # BaseSkill + skill() factory + Registry
├── decision/                   # LLMStructuredClassifier + ToolPlanner
├── orchestration/              # AgentOrchestrator（4-phase routing）
│   ├── orchestrator.ts         #   主類
│   ├── intent.ts               #   Deterministic + LLMFallback
│   ├── executor.ts             #   BaseDirectExecutor
│   ├── pipeline.ts             #   AgentPipeline（串接處理）
│   ├── fanout.ts               #   AgentFanout（並行派工）
│   ├── handoff.ts              #   AgentHandoffLoop（agent 轉接）
│   ├── channel.ts              #   ChannelAdapter
│   ├── pending.ts              #   PendingStateManager
│   ├── session-state.ts        #   AgentSessionState
│   ├── trace.ts                #   AgentDecisionTrace
│   └── result.ts               #   OrchestrationResult
└── index.ts                    # public exports
```

---

## 設計原則

1. **最小到最大** — 單一 agent 零開銷啟動，按需加層。不強迫用 orchestrator。
2. **可插拔** — LLM、Memory、Session、Knowledge、Guardrail、IntentResolver 全是介面，可替換實作
3. **per-user 記憶** — 所有操作以 `user_id` 為 scope，記憶自動提取和去重
4. **Stateless 部署** — Session Store 讓任何 instance 處理任何 request
5. **容錯優先** — Session/Memory 操作失敗降級而非崩潰
6. **Token 效率** — Prompt caching + 意圖分類 + 工具篩選 + 快速路徑，最小化 LLM 調用
7. **雙版本一致** — Python 和 TypeScript API 對齊，概念可直接遷移

## License

MIT
