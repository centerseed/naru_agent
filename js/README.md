# naru-agent-js

輕量 TypeScript Agent 框架，支援 orchestration、記憶、RAG、技能、護欄及結構化決策模式。基於 [Vercel AI SDK](https://sdk.vercel.ai/) 建構，支援 100+ LLM 供應商。

從單一 agent 到 Swarm 風格的多 agent 路由，同一個框架全部涵蓋。

## 安裝

```bash
npm install naru-agent-js
# peer deps（選擇你的 LLM 供應商）
npm install @ai-sdk/anthropic
```

---

## 架構

```
┌─────────────────────────────────────────────────────────┐
│ AgentOrchestrator（可選的協作層）                         │
│                                                         │
│ Phase 0: Pending Confirmation（待確認攔截）               │
│ Phase 1: Intent Resolution（確定性 + LLM 分類）          │
│ Phase 2: Direct Execution（高信心度跳過 LLM）            │
│ Phase 3: Delegate（路由到對應的 NaruAgent）               │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────┐
│ NaruAgent（核心 agent，可獨立使用）                       │
│                                                         │
│  Tools ─ Skills ─ Memory ─ Knowledge(RAG)               │
│  Session ─ Guardrails ─ Compression ─ Tracing           │
└─────────────────────────────────────────────────────────┘
```

---

## 快速開始

### 單一 Agent

```typescript
import { NaruAgent } from "naru-agent-js";
import { anthropic } from "@ai-sdk/anthropic";

const agent = new NaruAgent({
  model: anthropic("claude-sonnet-4-5"),
  instructions: ["你是一個實用的助手。"],
});

const result = await agent.chat("你好！", "session-1");
console.log(result.content);
```

### 多 Agent 協作

```typescript
import {
  AgentOrchestrator,
  NaruAgent,
  DeterministicIntentResolver,
  LLMFallbackIntentResolver,
  InMemoryPendingStateManager,
} from "naru-agent-js";

// 各自擁有不同 tools/skills 的專職 agent
const taskAgent = new NaruAgent({ model, tools: [brainDumpTool], instructions: ["你負責任務記錄。"] });
const calAgent  = new NaruAgent({ model, tools: [calendarTool], instructions: ["你負責行事曆查詢。"] });
const general   = new NaruAgent({ model, instructions: ["你是通用助手。"] });

// 基於意圖的路由
const orchestrator = new AgentOrchestrator({
  delegate: general,                              // 預設 fallback
  delegates: new Map([
    ["task_capture", taskAgent],
    ["calendar_query", calAgent],
  ]),
  intentResolver: new LLMFallbackIntentResolver({
    primary: new DeterministicIntentResolver([     // 零 LLM 成本
      { pattern: /記一下|待辦|todo/i, intent: { object: "task_capture", confidence: 1.0 } },
      { pattern: /行事曆|會議|schedule/i, intent: { object: "calendar_query", confidence: 1.0 } },
    ]),
    fallbackAgent: classifierAgent,                // 模糊訊息走 LLM fallback
  }),
  pendingStateManager: new InMemoryPendingStateManager(),
});

const result = await orchestrator.chat("記一下明天要買牛奶", { sessionId: "s1" });
// → taskAgent 處理此訊息
// result.trace.delegateUsed === "taskAgent"
// result.trace.phaseReached === "delegate"
```

### 最小 Orchestrator（零開銷）

```typescript
// 僅包裝現有 agent — 行為與 agent.chat() 完全一致
const orchestrator = new AgentOrchestrator({ delegate: myAgent });
const result = await orchestrator.chat("Hello");
```

---

## 核心功能

### 對話（`agent.chat`）

標準對話模式，完整的上下文管線 — 記憶、知識檢索、技能、工具呼叫、護欄。

```typescript
const result = await agent.chat("天氣如何？", "session-1", {
  userId: "user-123",
});
// result.content, result.usage, result.blocked
```

### 決策模式（`agent.decide`）

回傳型別化的 JSON 決策而非自然語言。使用完整的預取管線但跳過工具執行 — 適合路由、分類和評分。

```typescript
import { LLMStructuredClassifier } from "naru-agent-js";
import { z } from "zod";

const classifier = new LLMStructuredClassifier({
  model: anthropic("claude-haiku-4-5"),
  schema: z.object({
    intent: z.enum(["question", "complaint", "feedback"]),
    urgency: z.number().min(1).max(5),
  }),
  systemPrompt: "分類使用者訊息。",
});

const result = await agent.decide("我的訂單還沒到！", classifier);
console.log(result.decision);
// { intent: "complaint", urgency: 4 }
```

### 工具規劃器（ToolPlanner）

決定要呼叫哪些工具（含參數）但不執行。適合預覽、稽核或非同步派發。

```typescript
import { ToolPlanner } from "naru-agent-js";

const planner = new ToolPlanner({ model: anthropic("claude-haiku-4-5") });
const plan = await planner.plan("訂一張去東京的機票", myTools);
// [{ tool: "search_flights", args: { destination: "Tokyo" } }]
```

### 工具（Tools）

```typescript
import { tool } from "naru-agent-js";
import { z } from "zod";

const weatherTool = tool({
  name: "get_weather",
  description: "查詢城市目前天氣",
  parameters: z.object({ city: z.string() }),
  execute: async ({ city }) => `${city} 天氣：晴天 22°C`,
});

const agent = new NaruAgent({ model, tools: [weatherTool] });
```

### 記憶（Memory）

```typescript
import { MemoryManager, ChromaMemoryStore } from "naru-agent-js";

const memory = new MemoryManager({
  store: new ChromaMemoryStore({ collectionName: "user-memory" }),
  model: myModel,
});

const agent = new NaruAgent({ model, memoryManager: memory });
```

### 知識庫（RAG）

```typescript
import { ChromaKnowledgeStore } from "naru-agent-js";

const knowledge = new ChromaKnowledgeStore({
  collectionName: "docs",
  embedFn: myEmbedFn,
  contextualRetrieval: true, // Anthropic Contextual Retrieval
});

await knowledge.ingest([{ content: "...", metadata: {} }]);
const agent = new NaruAgent({ model, knowledgeStore: knowledge });
```

### 技能（Skills）

```typescript
import { skill } from "naru-agent-js";

const summarySkill = skill({
  name: "summarize",
  description: "摘要內容",
  triggers: ["摘要", "重點", "tldr"],
  priority: 10,
  run: async (message, context) => ({
    promptInjection: "請簡潔地摘要內容。",
    skillName: "summarize",
  }),
});

const agent = new NaruAgent({ model, skills: [summarySkill] });
```

### 護欄（Guardrails）

```typescript
import { KeywordGuardrail } from "naru-agent-js";

const agent = new NaruAgent({
  model,
  guardrails: [new KeywordGuardrail({ blocklist: ["spam", "abuse"] })],
});
```

### Session 管理

```typescript
import { InMemorySessionStore, RedisSessionStore } from "naru-agent-js";

// 開發環境
const agent = new NaruAgent({ model, sessionStore: new InMemorySessionStore() });

// 生產環境（多 instance）
const agent = new NaruAgent({
  model,
  sessionStore: new RedisSessionStore({ url: process.env.REDIS_URL }),
});
```

### 串流（Streaming）

```typescript
for await (const event of agent.stream("你好！", "session-1")) {
  if (event.type === "text_delta") process.stdout.write(event.text);
  if (event.type === "done") console.log("\n完成：", event.result.usage);
}
```

### 上下文壓縮（Context Compression）

```typescript
import { ContextCompressor, InMemorySummaryStore } from "naru-agent-js";

const agent = new NaruAgent({
  model,
  contextCompressor: new ContextCompressor({
    store: new InMemorySummaryStore(),
    model: myModel,
    triggerTokens: 4000,
  }),
});
```

### 追蹤（Tracing）

```typescript
import { TraceCollector, JsonlTraceExporter } from "naru-agent-js";

const tracer = new TraceCollector({
  exporter: new JsonlTraceExporter({ path: "./traces.jsonl" }),
});

const agent = new NaruAgent({ model, traceCollector: tracer });
```

---

## Orchestration API（開發中）

### AgentOrchestrator

透過 4 階段管線路由訊息的協作層。

```typescript
const orchestrator = new AgentOrchestrator<MyIntentType>({
  // 必要
  delegate: defaultAgent,

  // 多 agent 路由（可選）
  delegates: new Map([["intent_name", specializedAgent]]),

  // 意圖解析（可選）
  intentResolver: myResolver,

  // 快速路徑執行（可選）
  directExecutors: [myExecutor],

  // 狀態管理（可選）
  pendingStateManager: new InMemoryPendingStateManager(),
  sessionStateStore: new InMemorySessionStateStore(),

  // Channel 整合（可選）
  channelAdapter: myChannelAdapter,

  // 生命週期 hooks（可選）
  lifecycleHooks: {
    beforeMessage: async (msg, opts) => { /* 日誌、認證等 */ },
    afterMessage: async (result) => { /* 指標、分析 */ },
    onError: async (error) => { /* 告警 */ },
  },
});
```

### OrchestrationResult

擴展 `NaruResult`，加上 orchestration 後設資料：

| 欄位 | 型別 | 說明 |
|------|------|------|
| `content` | `string` | 回覆文字（繼承自 NaruResult） |
| `blocked` | `boolean` | 是否被護欄攔截（繼承自 NaruResult） |
| `usage` | `TokenUsage` | Token 用量（繼承自 NaruResult） |
| `toolCalls` | `string[]` | 使用的工具（繼承自 NaruResult） |
| `intent` | `IntentResult<T> \| null` | 解析出的意圖 |
| `trace` | `AgentDecisionTrace` | 完整決策追蹤含各階段耗時 |
| `pendingConfirmation` | `PendingState \| null` | 等待使用者確認 |
| `sessionId` | `string \| null` | Session 識別碼 |

### 自訂意圖型別

```typescript
import { GenericIntentObject } from "naru-agent-js";

// 以領域特定意圖擴展
type MyIntent = GenericIntentObject | "task_capture" | "calendar_query" | "reorganize";

// 所有 orchestration 類別完全型別化
const resolver = new DeterministicIntentResolver<MyIntent>([...]);
const orchestrator = new AgentOrchestrator<MyIntent>({ delegate, intentResolver: resolver });
// result.intent?.object 型別為 MyIntent
```

### ChannelAdapter

平台特定訊息處理的抽象介面：

```typescript
interface ChannelAdapter<TIn, TOut> {
  parseIncoming(input: TIn): ChannelMessage;
  formatOutgoing(result: OrchestrationResult): TOut;
  loadPendingState(sessionId: string): Promise<PendingState | null>;
  savePendingState(sessionId: string, state: PendingState): Promise<void>;
  clearPendingState(sessionId: string): Promise<void>;
}

// 使用方式
const result = await orchestrator.processChannel(rawLineWebhookEvent);
```

---

## Vercel / Edge Runtime

所有 I/O 透過 Vercel AI SDK — 可在 Next.js API routes、Edge functions 和 serverless 環境中運作。

## 更新日誌

### 0.2.0（開發中）
- **AgentOrchestrator** — 4 階段路由：pending → intent → direct execute → delegate
- **DeterministicIntentResolver** — 零成本 keyword/regex 意圖匹配
- **LLMFallbackIntentResolver** — 確定性 + LLM fallback 組合
- **BaseDirectExecutor** — 高信心度操作跳過 LLM
- **ChannelAdapter** — 抽象 channel 介面（LINE、Slack、API 等）
- **PendingStateManager** — 多步驟確認流程
- **AgentSessionState** — 實體追蹤用於指代消解
- **多 agent 路由** — intent-to-delegate 映射給專職 agent
- **TypeScript 泛型** — 完全型別化的自訂意圖型別

### 0.1.2
- **決策模式**（`agent.decide<T>`） — 具完整上下文管線的結構化 JSON 輸出
- **LLMStructuredClassifier** — 以 Zod schema 驅動的分類器含上下文組裝
- **ToolPlanner** — 不執行的工具規劃（dry-run）
- `agent.chat` 的 `skip` 參數可跳過 intent/skills/toolCalling

### 0.1.1
- 初始公開發布
- 具工具呼叫、記憶、RAG、技能、護欄、串流、追蹤的 ReAct agent

## 授權

MIT
