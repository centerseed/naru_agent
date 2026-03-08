# naru_agent

輕量、可插拔的 Python Agent 框架，支援 per-user 記憶、tool calling、guardrails、streaming。設計為 git submodule 嵌入各專案使用。

## 架構

```
naru_agent/
├── agent.py              # Agent 定義
├── runner.py             # ReAct 執行引擎（sync + async streaming）
├── streaming.py          # StreamEvent 類型定義
├── events.py             # 輕量事件匯流排
├── llm/
│   ├── base.py           # LLM 抽象介面（chat + chat_stream）
│   └── litellm_provider.py  # LiteLLM 實作（100+ models, prompt caching, streaming）
├── memory/
│   ├── base.py           # MemoryStore 介面
│   ├── manager.py        # LLM 驅動的事實提取 + 和解
│   ├── mem0_manager.py   # Mem0MemoryManager（三層記憶）
│   ├── prompts.py        # 記憶用 prompt templates
│   └── stores/
│       └── chroma.py     # ChromaDB 後端
├── session/
│   ├── base.py           # BaseSessionStore 抽象介面
│   ├── memory_store.py   # InMemorySessionStore（單 process）
│   └── redis_store.py    # RedisSessionStore（多 instance 部署）
├── knowledge/
│   ├── base.py           # BaseKnowledgeStore 介面
│   ├── chroma_store.py   # ChromaDB 向量搜索 + Contextual Retrieval
│   ├── contextualizer.py # Contextual Retrieval 實作
│   ├── graph_extractor.py # LLM 實體/關係提取
│   ├── graph_store.py    # NetworkX 知識圖譜
│   └── hybrid_store.py   # 多源知識融合
├── tools/
│   ├── base.py           # BaseTool + @tool 裝飾器（sync + async）
│   └── builtin/
│       └── rag.py        # 通用 RAG 查詢工具
├── tool_selection/
│   ├── base.py           # BaseToolSelector 介面 + ToolSelectionResult
│   └── embedding.py      # Embedding 相似度篩選（optional dep）
├── guardrails/
│   ├── base.py           # Guardrail 介面
│   └── keyword.py        # 關鍵字/正則 guardrail
├── intent/
│   ├── base.py           # BaseIntentClassifier 介面 + IntentResult
│   ├── llm_classifier.py # LLM 驅動的意圖分類
│   └── tool_calling_classifier.py  # Tool calling 版本
├── compression/
│   ├── base.py           # BaseSummaryStore 介面
│   ├── compressor.py     # ContextCompressor（背景對話壓縮）
│   ├── memory_store.py   # InMemory summary store
│   └── redis_store.py    # Redis summary store
├── skills/
│   ├── base.py           # BaseSkill + @skill 裝飾器 + SkillContext/SkillResult
│   ├── registry.py       # SkillRegistry（統一管理）
│   └── selectors.py      # KeywordSkillSelector / EmbeddingSkillSelector
└── tracing/
    ├── trace.py          # Trace（完整 call 記錄）
    ├── span.py           # Span（單一操作片段）
    ├── collector.py      # TraceCollector（蒐集 + 導出）
    └── exporters/
        └── jsonl.py      # JSONL 導出器
```

## 安裝

作為 git submodule：

```bash
cd your-project
git submodule add <naru_agent_repo_url> naru_agent
pip install pydantic litellm chromadb
```

---

## 核心元件

### Agent

`Agent` 是框架的核心設定物件，定義 agent 的身份、能力和行為：

- **`name`** — agent 識別名稱
- **`role`** — agent 的角色定義（注入 system prompt）
- **`goal`** — agent 的目標描述（注入 system prompt）
- **`system_prompt`** — 自訂 system prompt（會疊加在 role/goal 之上）
- **`llm`** — LLM provider 實例（`LiteLLMProvider` 或自訂）
- **`tools`** — 工具清單（`BaseTool` 或 `@tool` 裝飾的函數）
- **`memory`** — 記憶管理器（`MemoryManager` 或 `Mem0MemoryManager`）
- **`knowledge_store`** — 知識庫（`ChromaKnowledgeStore`、`GraphKnowledgeStore` 等）
- **`guardrails`** — 防護規則清單（`BaseGuardrail` 實例）
- **`skills`** — Skill 清單（`BaseSkill` 實例）
- **`intent_classifier`** — 意圖分類器（可選，用於跳過不必要的 RAG/tool calls）
- **`max_iterations`** — ReAct 最大迭代次數（預設 10）

---

### Runner

`Runner` 負責執行 agent 的 ReAct 推理迭代，管理 tool calls 和 session 歷史。

**`Runner.run(message, user_id, session_id, session_store)`**
- 同步執行，回傳 `RunResult`（含 `content`、`usage`、`tool_calls`）
- 多 tool calls 自動並行（`ThreadPoolExecutor`）

**`Runner.run_stream(message, user_id, session_id, session_store)`**
- async generator，依序 yield `StreamEvent`
- 多 tool calls 自動並行（`asyncio.gather`）
- session 在開始時讀取、結束時寫回（成功/失敗皆安全）

---

### LLM

**`LiteLLMProvider`** — 透過 LiteLLM 支援 100+ 模型（Gemini、OpenAI、Anthropic、Ollama 等）：

- **模型切換** — 僅需更換 model string，其餘不變
- **Prompt caching** — Anthropic 模型自動啟用 system message 的 `cache_control`，減少重複 token 開銷；非 Anthropic 模型正常運作，可明確傳 `enable_cache=False` 關閉
- **Streaming** — 支援 `chat_stream()` async generator
- **`cache_creation_input_tokens` / `cache_read_input_tokens`** — cache 用量自動記錄在 `RunResult.usage`

繼承 `BaseLLMProvider` 可接入任意 LLM 後端。

---

### 工具系統（Tools）

**`@tool` 裝飾器** — 將任意函數變成 agent 工具：

- 支援 sync 和 async 函數
- 自動從函數簽名生成 JSON schema
- `description` 參數作為 LLM 的工具說明
- 繼承 `BaseTool` 可自訂更複雜的工具

**並行執行** — 同一輪 LLM 回應中的多個 tool calls 自動並行：
- sync runner：`ThreadPoolExecutor`
- async runner：`asyncio.gather`

**內建工具** — `naru_agent.tools.builtin.rag` 提供通用 RAG 查詢工具，自動銜接 `knowledge_store`。

---

### 記憶系統（Memory）

naru_agent 提供兩種記憶後端：

#### MemoryManager + ChromaDB（本地，適合開發）

- LLM 驅動的事實萃取：每次對話後，自動從對話中提取重要事實
- 智能和解：新事實與既有記憶衝突時，自動更新而非重複存儲
- per-user scope：所有記憶以 `user_id` 隔離
- ChromaDB 持久化：本地磁碟存儲，無需額外服務

#### Mem0MemoryManager + pgvector（生產環境，支援三層記憶）

使用 [mem0](https://github.com/mem0ai/mem0) 管理記憶，後端接 PostgreSQL（本地或 Neon）。

三種記憶模式：
- **語義記憶**（預設）— LLM 自動萃取重要事實，適合長期偏好和個人資訊
- **短期記憶** — 原始對話直接存入，不經 LLM 改寫（`infer=False`）
- **程序記憶** — Agent 從用戶回饋學習操作步驟（`memory_type="procedural_memory"`）

記憶自動注入 system prompt，Runner 會在每次 run 前讀取相關記憶。

繼承 `MemoryStore` 可接入 PostgreSQL、Redis 等自訂後端。

---

### Session 管理

Session Store 讓 runner 在無狀態 stateless 部署中維護多輪對話歷史：

**`InMemorySessionStore`** — 單 process 使用，適合開發和單機部署

**`RedisSessionStore`** — 多 instance 部署，任何 instance 都能繼續任何 session：
- 可設定 `ttl` 控制 session 過期時間
- session 開始時讀取、結束時寫回

容錯設計：
- `get()` 失敗 → 降級為無歷史，不中斷 stream
- `save()` 失敗 → 仍然 yield `DoneEvent`，不遺失回應
- 資料損壞 → 回傳 None，自動重建 session

繼承 `BaseSessionStore` 可接入 PostgreSQL 等自訂後端。

---

### 知識系統（Knowledge）

naru_agent 提供三種知識檢索策略：

| 策略 | 適用場景 | 額外開銷 |
|------|----------|----------|
| **ChromaKnowledgeStore**（向量搜索） | 文件查詢、FAQ、產品搜索 | 低（embedding 計算） |
| **GraphKnowledgeStore**（知識圖譜） | 需要推理的場景：醫療、法律、複雜業務流程 | 高（每次 ingest/search 呼叫 LLM） |
| **HybridKnowledgeStore**（混合） | 同時需要語義搜索和關係推理 | 兩者之和 |

#### ChromaKnowledgeStore（向量搜索）

- **Contextual Retrieval**（Anthropic 論文）— ingest 時 LLM 自動為每個 chunk 生成上下文描述，降低 49-67% 檢索失敗率
- `ingest_markdown_dir()` — 批次攝取整個目錄的 Markdown 文件，自動分 chunk
- `search(query, top_k)` — 語義向量搜索
- ChromaDB 持久化

#### GraphKnowledgeStore（知識圖譜）

- **GraphExtractor** — LLM 驅動的實體識別和關係提取，支援自訂提取模型
- **NetworkX 圖結構** — 以 `nx.DiGraph` 存儲實體和關係，支援圖遍歷
- `ingest_markdown_dir()` — 自動提取文件中的實體和關係
- `save()` / `load()` — 持久化至磁碟（pickle）
- `store.graph` — 直接存取底層 `nx.DiGraph`，查詢節點/邊/關係

#### HybridKnowledgeStore（混合）

- 組合多個 KnowledgeStore（向量 + 圖譜）
- 可設定各 store 的 `weights` 調整排序權重
- 結果去重後統一回傳

> **注意**：知識圖譜的 LLM 開銷顯著高於向量搜索，建議使用便宜快速的模型做實體提取（如 `gemini/gemini-2.5-flash-lite`）。

繼承 `BaseKnowledgeStore` 可接入任意自訂知識後端。

---

### Guardrails（防護）

Guardrail 在輸入/輸出兩個層級攔截和過濾內容：

**`KeywordGuardrail`** — 關鍵字/正則表達式防護：
- `blocked_patterns` — 輸入觸發阻擋的正則模式
- `input_message` — 輸入被阻擋時回傳給用戶的訊息
- `output_replacement` — 輸出被偵測到時的替換文字

繼承 `BaseGuardrail` 可自訂任意邏輯（如 LLM 語意判斷）：
- `check_input(message) -> GuardrailResult`
- `check_output(response) -> GuardrailResult`
- `GuardrailResult.modified_text` — 替換文字；`reason` — 阻擋原因

---

### Tool Selection（動態工具篩選）

當工具數量多時（>10），Tool Selection 用 embedding 相似度在每次迭代中只挑出最相關的 top-k 個工具送給 LLM，節省 tokens 並提升工具選擇準確率。

**`EmbeddingToolSelector`** — 主要實作：
- `embed_fn` — 任意 embedding 函數（`litellm_embed_fn()` 、sentence-transformers 等）
- `top_k` — 每次最多選幾個工具（預設 5）
- **跨迭代追蹤** — 已使用的工具在後續迭代中自動保留（上限 top_k/2）
- **embedding cache** — tool embeddings 自動 cache，description 變更時自動失效
- **smart fallback** — 工具數少於 top_k 時自動跳過篩選

**`litellm_embed_fn(model)`** — 工廠函數，回傳 LiteLLM embedding 函數，預設 `gemini/text-embedding-004`

特性：
- **opt-in** — 不傳 `tool_selector` 時行為完全不變
- **pluggable** — 繼承 `BaseToolSelector` 可自訂策略

---

### Intent Classification（意圖分類）

在執行 RAG 和 tool calls 前，先快速分類用戶意圖，跳過不必要的操作：

**`IntentResult`** — 分類結果：
- `needs_knowledge` — 是否需要 RAG 知識庫查詢
- `needs_tools` — 是否需要 tool calls

**`LLMIntentClassifier`** — LLM 驅動的意圖分類：
- 使用輕量模型（預設 `gemini/gemini-2.5-flash-lite`）做快速分類
- 支援 few-shot `examples` 自訂領域偏好
- 分類失敗時 fallback 為全部啟用（安全降級）

**`ToolCallingClassifier`** — 使用 LLM tool calling 能力做分類，更結構化。

繼承 `BaseIntentClassifier` 可自訂分類邏輯。

---

### Skills（技能系統）

Skills 讓 agent 在執行前根據用戶訊息動態注入行為，不修改核心 Agent 定義：

**`@skill` 裝飾器** — 將函數變成 Skill：
- `name` — 技能名稱
- `description` — 技能描述
- `triggers` — 關鍵字列表（用於 KeywordSkillSelector 匹配）
- `priority` — 優先順序（數字越大越優先）
- `always_active` — 是否無條件啟用

**`SkillContext`** — 執行時傳入 skill 的上下文：
- `message`、`user_id`、`session_id`
- `memory_context` — 當前用戶記憶文字
- `knowledge_store` — 可呼叫 `get_knowledge(query)` 查詢知識庫

**`SkillResult`** — Skill 回傳值：
- `prompt_injection` — 注入 system prompt 的額外文字
- `extra_tools` — 動態增加的工具
- `override_system_prompt` — 完全替換 system prompt

**Skill Selectors** — 控制哪些 skills 被啟用：
- `KeywordSkillSelector` — 關鍵字觸發匹配（快速，無 API 成本）
- `EmbeddingSkillSelector` — embedding 相似度選取（更語義化，可設定 `top_k` 和 `similarity_threshold`）

---

### Context Compression（對話壓縮）

長對話自動在背景壓縮，避免 context window 過長：

**`ContextCompressor`** — 核心壓縮器：
- `threshold_rounds` — 達到幾輪後開始壓縮（預設 5）
- `keep_last_rounds` — 保留最近幾輪完整對話（預設 5）
- `summary_model` — 壓縮用模型（預設 `gemini/gemma-3-12b-it`）
- 壓縮在背景線程執行，不阻塞主流程
- 摘要自動注入下一輪對話的 context

**Summary Stores** — 摘要持久化：
- `InMemorySummaryStore` — 單 process
- `RedisSummaryStore` — 多 instance 部署

---

### Tracing（追蹤）

記錄每次 agent call 的完整執行鏈路，用於觀測、debug 和品質分析：

**`Trace`** — 單次 call 的完整記錄：
- `trace_id`、`thread_id`（session）、`user_id`
- `input`、`output`、`blocked`（是否被 guardrail 攔截）
- `usage` — token 用量（含 cache）
- `intent` — 意圖分類結果
- `tool_calls` — 呼叫的工具名稱列表
- `spans` — 各操作片段的詳細時間記錄
- `duration_ms` — 總執行時間
- `to_dict()` / `to_json()` — 序列化輸出

**`Span`** — 單一操作片段（LLM call、tool call 等）

**`TraceCollector`** — 蒐集 trace 並透過 exporter 導出

**`JsonlTraceExporter`** — 將 trace 以 JSONL 格式寫入磁碟，每行一個 JSON

---

### Streaming Events

`Runner.run_stream()` 產生的事件類型：

| 事件 | 說明 | 主要欄位 |
|------|------|----------|
| `TextDeltaEvent` | LLM 輸出的文字片段 | `delta` |
| `ToolCallStartEvent` | 開始呼叫工具 | `name`、`arguments` |
| `ToolResultEvent` | 工具執行完成 | `name`、`result` |
| `DoneEvent` | 整個 run 完成 | `content`、`usage` |
| `ErrorEvent` | 執行錯誤 | `error` |

---

### 事件匯流排（EventBus）

輕量事件系統，用於監控和埋點，不影響主流程：

支援事件類型：`after_llm_call`、`after_tool_call`、`tool_selection`

`bus.on(event, callback)` — 訂閱事件；`Runner(agent, event_bus=bus)` — 掛載到 runner。

---

## 設計原則

1. **最小依賴** — 核心只需 pydantic + litellm + chromadb
2. **可插拔** — LLM、Memory Store、Session Store、Guardrail、Tool Selector、Knowledge Store 都是介面，可替換實作
3. **per-user 記憶** — 所有操作以 `user_id` 為 scope，記憶自動提取和去重
4. **Stateless 部署** — Session Store 讓任何 instance 都能處理任何 request，不需 sticky session
5. **容錯優先** — Session/Memory 操作失敗時降級而非崩潰，stream 不會因基礎設施問題中斷
6. **Tool 就是函數** — `@tool` 裝飾器讓任何函數變成 agent 工具，sync/async 皆可
7. **Token 效率** — Prompt caching + 動態工具篩選 + 意圖分類，減少無謂的 token 開銷
8. **並行執行** — 多 tool calls 自動並行（sync: ThreadPoolExecutor, async: asyncio.gather）
