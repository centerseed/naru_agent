# naru_agent

輕量、可插拔的 Python agent 框架，支援 per-user 記憶、tool calling、guardrails。設計為 git submodule 嵌入各專案使用。

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
│   ├── prompts.py        # 記憶用 prompt templates
│   └── stores/
│       └── chroma.py     # ChromaDB 後端
├── session/
│   ├── base.py           # BaseSessionStore 抽象介面
│   ├── memory_store.py   # InMemorySessionStore（單 process）
│   └── redis_store.py    # RedisSessionStore（多 instance 部署）
├── tools/
│   ├── base.py           # BaseTool + @tool 裝飾器（sync + async）
│   └── builtin/
│       └── rag.py        # 通用 RAG 查詢工具
├── tool_selection/
│   ├── base.py           # BaseToolSelector 介面 + ToolSelectionResult
│   └── embedding.py      # Embedding 相似度篩選（optional dep）
└── guardrails/
    ├── base.py           # Guardrail 介面
    └── keyword.py        # 關鍵字/正則 guardrail
```

## 安裝

作為 git submodule：

```bash
cd your-project
git submodule add <naru_agent_repo_url> naru_agent
pip install pydantic litellm chromadb
```

## 整合範例

### Health123 — 健康產品推薦聊天機器人

```python
from naru_agent import Agent, Runner, tool, MemoryManager
from naru_agent.llm import LiteLLMProvider
from naru_agent.guardrails import KeywordGuardrail
from naru_agent.memory.stores.chroma import ChromaMemoryStore

# 1. LLM
llm = LiteLLMProvider(model="gemini/gemini-2.5-flash-lite")

# 2. 自定義工具：包裝現有的 ChromaDB 產品搜索
@tool(description="根據用戶問題搜索健康產品資料庫，回傳最相關的產品資訊")
def search_products(query: str) -> str:
    # 包裝你現有的 ChromaDB 查詢邏輯
    import chromadb
    client = chromadb.PersistentClient(path="./chroma_db")
    collection = client.get_collection("products")
    results = collection.query(query_texts=[query], n_results=3)
    return "\n\n".join(results["documents"][0])

# 3. 醫療建議防護
medical_guard = KeywordGuardrail(
    blocked_patterns=[
        r"處方", r"劑量", r"診斷", r"治療方案",
        r"應該吃\d+.*毫克", r"停藥", r"替代.*藥物",
    ],
    input_message="我是健康產品顧問，無法提供醫療建議。建議您諮詢專業醫療人員。",
    output_replacement="（此部分涉及醫療建議，建議您諮詢專業醫療人員以獲得準確指導。）",
)

# 4. 記憶系統：記住用戶健康狀況和偏好
def embed(text: str) -> list[float]:
    import google.genai as genai
    result = genai.Client().models.embed_content(
        model="gemini-embedding-001", contents=text
    )
    return result.embeddings[0].values

memory = MemoryManager(
    llm=llm,
    store=ChromaMemoryStore(persist_dir="./health123_memory"),
    embed_fn=embed,
)

# 5. 組裝 Agent
agent = Agent(
    name="health_consultant",
    role="大醫生技健康產品顧問",
    goal="根據用戶需求推薦最適合的健康產品",
    system_prompt="""你是大醫生技的專業健康顧問，像朋友一樣親切地為用戶推薦產品。
規則：
- 只根據產品資料庫中的資訊回答
- 不主動報價，除非用戶詢問
- 絕不提供醫療診斷或處方建議
- 找不到資料時誠實說需要確認""",
    llm=llm,
    tools=[search_products],
    memory=memory,
    guardrails=[medical_guard],
)

# 6. 執行
runner = Runner(agent)
result = runner.run(
    user_id="user_abc",
    message="我最近膝蓋不太舒服，有什麼保養品推薦嗎？",
)
print(result.content)
```

### Paceriz — 個人化訓練建議

```python
from naru_agent import Agent, Runner, tool, MemoryManager
from naru_agent.llm import LiteLLMProvider
from naru_agent.memory.stores.chroma import ChromaMemoryStore

llm = LiteLLMProvider(model="gemini/gemini-2.5-flash-lite")

@tool(description="查詢指定用戶最近 N 天的訓練歷史紀錄")
def get_training_history(user_id: str, days: int = 30) -> str:
    # 呼叫你的 Paceriz API 或資料庫
    return "最近30天：深蹲3次、臥推2次、跑步5次..."

@tool(description="查詢用戶當前的訓練課表")
def get_schedule(user_id: str) -> str:
    return "週一：胸+三頭、週三：背+二頭、週五：腿..."

@tool(description="查詢用戶最近的課表修改紀錄")
def get_schedule_changes(user_id: str, days: int = 14) -> str:
    return "2/20: 將腿部訓練從週五改到週六、2/18: 新增週日有氧..."

memory = MemoryManager(
    llm=llm,
    store=ChromaMemoryStore(persist_dir="./paceriz_memory"),
    embed_fn=your_embed_fn,
)

agent = Agent(
    name="training_advisor",
    role="私人教練助手",
    goal="根據用戶的訓練歷史和身體狀況，提供個人化的訓練建議",
    system_prompt="""你是專業的健身教練助手。
- 根據用戶的訓練歷史和課表給予建議
- 注意用戶的傷病史和體能限制（從記憶中取得）
- 避免推薦可能加重傷病的動作
- 建議要具體、可執行""",
    llm=llm,
    tools=[get_training_history, get_schedule, get_schedule_changes],
    memory=memory,
)

runner = Runner(agent)
# 記憶會自動累積：用戶的偏好、傷病史、訓練習慣
result = runner.run(
    user_id="athlete_456",
    message="我今天想練腿但膝蓋有點不舒服，怎麼調整？",
)
print(result.content)
```

### Zentropy — 智慧分類 Agent

```python
from naru_agent import Agent, Runner, tool, MemoryManager
from naru_agent.llm import LiteLLMProvider
from naru_agent.memory.stores.chroma import ChromaMemoryStore

llm = LiteLLMProvider(model="gemini/gemini-2.5-flash-lite")

@tool(description="取得待分類的項目列表")
def get_pending_items(limit: int = 10) -> str:
    # 呼叫 Zentropy API
    return '[{"id": "item_1", "title": "React Hook 教學", "content": "..."}]'

@tool(description="將項目分類到指定類別")
def classify_item(item_id: str, category: str, confidence: float = 1.0) -> str:
    # 呼叫 Zentropy API 執行分類
    return f"已將 {item_id} 分類到 {category}"

@tool(description="查詢用戶的分類體系和現有類別")
def get_categories(user_id: str) -> str:
    return '["技術/前端", "技術/後端", "設計", "商業/行銷", "個人筆記"]'

# 記憶系統學習用戶的分類偏好
memory = MemoryManager(
    llm=llm,
    store=ChromaMemoryStore(persist_dir="./zentropy_memory"),
    embed_fn=your_embed_fn,
)

agent = Agent(
    name="smart_classifier",
    role="智慧分類助手",
    goal="學習用戶的分類意圖，越來越準確地自動分類",
    system_prompt="""你是一個智慧分類助手。
- 根據用戶的分類體系和歷史偏好來分類新項目
- 當不確定時，詢問用戶而不是猜測
- 記住用戶的修正，下次同類項目要分對
- 可以建議新類別，但需要用戶確認""",
    llm=llm,
    tools=[get_pending_items, classify_item, get_categories],
    memory=memory,
)

runner = Runner(agent)
# Agent 記住：「用戶把 React 相關文章都放在 技術/前端」
# 下次遇到 React 文章，自動分到正確類別
result = runner.run(
    user_id="user_789",
    message="幫我分類這批新收藏的文章",
)
print(result.content)
```

## Streaming + Session 管理

`Runner.run_stream()` 提供 async streaming，搭配 `SessionStore` 實現 stateless 多 instance 部署。

### 基本 Streaming

```python
from naru_agent import Runner

runner = Runner(agent)

async for event in runner.run_stream("你好"):
    if event.type == "text_delta":
        print(event.delta, end="", flush=True)
    elif event.type == "tool_call_start":
        print(f"\n[calling {event.name}...]")
    elif event.type == "tool_result":
        print(f"[{event.name} → {event.result[:50]}]")
    elif event.type == "done":
        print(f"\n[tokens: {event.usage}]")
    elif event.type == "error":
        print(f"\n[error: {event.error}]")
```

事件類型：`TextDeltaEvent` → `ToolCallStartEvent` → `ToolResultEvent` → `DoneEvent` | `ErrorEvent`

### Session Store（多 instance 部署）

```
┌──────────┐     ┌──────────────┐     ┌──────────┐
│ Instance1│────▶│    Redis     │◀────│ Instance2│
│ (FastAPI)│     │              │     │ (FastAPI)│
└──────────┘     └──────────────┘     └──────────┘
     │                                      │
     └──── SessionStore.get(session_id) ────┘
           SessionStore.save(session_id)
```

每個 request 帶 `session_id`，`run_stream()` 開始時 load、結束時 save，任何 instance 都能處理：

```python
# Redis（生產環境）
from naru_agent.session.redis_store import RedisSessionStore
import redis.asyncio as aioredis

store = RedisSessionStore(
    aioredis.from_url("redis://localhost"),
    ttl=3600,  # session 1 小時過期
)

# 或 InMemory（開發/單 process）
from naru_agent.session import InMemorySessionStore
store = InMemorySessionStore()

# 搭配 streaming 使用
async for event in runner.run_stream(
    "接續上次對話",
    session_id="user_123_session_abc",
    session_store=store,
):
    yield event  # 轉發給 SSE / WebSocket
```

容錯設計：
- `session_store.get()` 失敗 → 降級為無歷史，不中斷 stream
- `session_store.save()` 失敗 → 仍然 yield `DoneEvent`，不遺失回應
- Redis 資料損壞 → 回傳 None，自動重建 session

### 並行工具執行

`Runner.run()` 和 `run_stream()` 都支援多工具並行執行：

```python
# sync 用 ThreadPoolExecutor，async 用 asyncio.gather
result = runner.run("查天氣和匯率")  # 兩個 tool 同時跑，不是依序等待
```

### 自定義 SessionStore

```python
from naru_agent.session.base import BaseSessionStore

class PostgresSessionStore(BaseSessionStore):
    async def get(self, session_id: str) -> list[dict] | None: ...
    async def save(self, session_id: str, history: list[dict]) -> None: ...
    async def delete(self, session_id: str) -> None: ...
```

## Tool Selection（動態工具篩選）

當工具數量多時（>10），每次 LLM 呼叫送出全部 schema 會浪費大量 tokens 並降低工具選擇準確率。Tool Selection 用 embedding 相似度在每次迭代中只挑出最相關的 top-k 個工具送給 LLM。

```python
from naru_agent import EmbeddingToolSelector, litellm_embed_fn, Runner

# 推薦：用 LiteLLM embedding（Gemini 免費，不需額外安裝）
selector = EmbeddingToolSelector(
    embed_fn=litellm_embed_fn(),  # 預設 gemini/text-embedding-004
    top_k=5,
)
runner = Runner(agent, tool_selector=selector)

# 也可指定其他 embedding model
selector = EmbeddingToolSelector(
    embed_fn=litellm_embed_fn("text-embedding-3-small"),  # OpenAI
    top_k=5,
)

# 或用本地 sentence-transformers（離線、零 API 成本，需 pip install naru_agent[embeddings]）
selector = EmbeddingToolSelector(top_k=5)  # 自動用 all-MiniLM-L6-v2
```

特性：
- **opt-in**：不傳 `tool_selector` 時行為完全不變
- **pluggable**：繼承 `BaseToolSelector` 可自訂策略
- **smart fallback**：工具少時自動跳過篩選
- **跨迭代追蹤**：已使用的工具在後續迭代中自動保留（上限 top_k/2）
- **cache**：tool embeddings 自動 cache，description/schema 變更時自動失效

## Prompt Caching

LiteLLMProvider 對 Anthropic 模型自動啟用 system message 的 `cache_control`，減少重複 token 開銷：

```python
from naru_agent.llm import LiteLLMProvider

# Anthropic 模型自動啟用 prompt caching
llm = LiteLLMProvider(model="anthropic/claude-sonnet-4-20250514")

# 非 Anthropic 模型不受影響（Gemini、OpenAI 等正常運作）
llm = LiteLLMProvider(model="gemini/gemini-2.5-flash-lite")

# 明確停用
llm = LiteLLMProvider(model="anthropic/claude-sonnet-4-20250514", enable_cache=False)
```

cache 相關的 usage（`cache_creation_input_tokens`、`cache_read_input_tokens`）會自動出現在 `RunResult.usage` 中。

## 事件監聽

```python
from naru_agent import EventBus

bus = EventBus()

# 監控 token 使用量
bus.on("after_llm_call", lambda data: print(f"LLM call #{data['iteration']}"))
bus.on("after_tool_call", lambda data: print(f"Tool: {data['tool']}"))
bus.on("tool_selection", lambda data: print(
    f"Tools: {data['selected_tools']}/{data['total_tools']} selected"
))

runner = Runner(agent, event_bus=bus)
```

## 自定義 Guardrail

```python
from naru_agent.guardrails.base import BaseGuardrail, GuardrailResult

class LLMGuardrail(BaseGuardrail):
    """用 LLM 判斷是否包含醫療建議（比關鍵字更準確）"""

    def __init__(self, llm):
        self.llm = llm

    def check_input(self, message: str) -> GuardrailResult:
        return GuardrailResult(passed=True)

    def check_output(self, response: str) -> GuardrailResult:
        result = self.llm.chat([
            {"role": "system", "content": "判斷以下回覆是否包含醫療診斷或處方建議。回覆 YES 或 NO。"},
            {"role": "user", "content": response},
        ])
        if "YES" in result.content.upper():
            return GuardrailResult(
                passed=False,
                modified_text="建議您諮詢專業醫療人員。",
                reason="LLM detected medical advice",
            )
        return GuardrailResult(passed=True)
```

## 自定義 Memory Store

```python
from naru_agent.memory.base import MemoryStore, MemoryItem

class PostgresMemoryStore(MemoryStore):
    """用 pgvector 做記憶存儲"""

    def add(self, item: MemoryItem, embedding: list[float]) -> None: ...
    def search(self, user_id: str, embedding: list[float], top_k: int = 5) -> list[MemoryItem]: ...
    def update(self, item_id: str, content: str, embedding: list[float]) -> None: ...
    def delete(self, item_id: str) -> None: ...
    def get_all(self, user_id: str) -> list[MemoryItem]: ...
```

## 記憶層 DB 設定

naru_agent 提供兩種記憶後端，依需求選擇：

### 方案 A：MemoryManager + ChromaDB（本地，適合開發）

自帶 LLM 驅動的事實萃取邏輯，DB 存在本機。

```python
from naru_agent import MemoryManager
from naru_agent.memory.stores.chroma import ChromaMemoryStore

def embed(text: str) -> list[float]:
    from google import genai
    result = genai.Client(api_key="YOUR_KEY").models.embed_content(
        model="models/gemini-embedding-001", contents=text
    )
    return result.embeddings[0].values

memory = MemoryManager(
    llm=llm,
    store=ChromaMemoryStore(persist_dir="./memory_db"),
    embed_fn=embed,
)
```

### 方案 B：Mem0MemoryManager + pgvector（生產環境，支援三層記憶）

使用 [mem0](https://github.com/mem0ai/mem0) 管理記憶，DB 可接 PostgreSQL（本地或 Neon）。

#### 安裝

```bash
pip install mem0ai psycopg2-binary
```

#### 設定 PostgreSQL（以 Neon 為例）

```python
from mem0 import Memory
from naru_agent.memory import Mem0MemoryManager

config = {
    "llm": {
        "provider": "litellm",
        "config": {"model": "gemini/gemini-2.5-flash-lite"},
    },
    "embedder": {
        "provider": "gemini",
        "config": {
            "model": "models/gemini-embedding-001",
            "api_key": "YOUR_GEMINI_API_KEY",
        },
    },
    "vector_store": {
        "provider": "pgvector",
        "config": {
            # Neon 請使用 non-pooler endpoint（避免與 mem0 內建 pool 衝突）
            "connection_string": "postgresql://user:pass@host/dbname?sslmode=require",
            "collection_name": "memories",       # 資料表名稱
            "embedding_model_dims": 768,          # gemini-embedding-001 = 768 維
        },
    },
    "version": "v1.1",
}

client = Memory.from_config(config)
memory = Mem0MemoryManager(client=client)
```

#### 設定本地 PostgreSQL + pgvector

```bash
# 用 Docker 啟動（已含 pgvector extension）
docker run -d \
  -e POSTGRES_USER=mem0 \
  -e POSTGRES_PASSWORD=mem0pass \
  -e POSTGRES_DB=mem0db \
  -p 5432:5432 \
  pgvector/pgvector:pg16
```

```python
config = {
    # ... llm / embedder 同上 ...
    "vector_store": {
        "provider": "pgvector",
        "config": {
            "host": "localhost",
            "port": 5432,
            "dbname": "mem0db",
            "user": "mem0",
            "password": "mem0pass",
            "collection_name": "memories",
            "embedding_model_dims": 768,
        },
    },
    "version": "v1.1",
}
```

#### 三層記憶使用方式

mem0 支援三種記憶模式，透過 `Mem0MemoryManager.add()` 的參數控制：

```python
# 1. 語義記憶（預設）：LLM 自動萃取重要事實
#    適合：長期偏好、個人資訊、反覆出現的主題
memory.add(user_id, messages)                    # infer=True 為預設值

# 2. 短期記憶：原始對話直接存入，不經 LLM 改寫
#    適合：需要保留完整原文、對話紀錄查詢
memory.add(user_id, messages, infer=False)

# 3. 程序記憶：Agent 學到的方法與操作步驟
#    適合：Agent 從用戶回饋學習如何執行任務
memory.add(
    user_id, messages,
    memory_type="procedural_memory",
    agent_id="my_agent",
)
```

#### 整合到 Agent

```python
from naru_agent import Agent, Runner

agent = Agent(
    name="Naru",
    role="assistant",
    llm=llm,
    memory=memory,   # 直接帶入，Runner 會自動存取和注入記憶
)

runner = Runner(agent)

# 第一次對話：記憶自動存進 pgvector
runner.run("我喜歡台式料理，不喜歡麻辣", user_id="user_123")

# 第二次對話：記憶自動從 DB 讀出，注入到 system prompt
runner.run("今天晚餐吃什麼好？", user_id="user_123")
```

#### 注意事項

| 項目 | 說明 |
|------|------|
| Neon 連線 | 使用 **non-pooler** endpoint，避免 mem0 內建 psycopg2 pool 與 Neon pooler 衝突 |
| 向量維度 | Gemini `gemini-embedding-001` = **768 維**；OpenAI `text-embedding-3-small` = **1536 維**，兩者不可混用 |
| 資料表 | mem0 自動建立，第一次執行時會在 DB 建立 `collection_name` 指定的資料表 |
| SSL | Neon 必須加 `?sslmode=require`；本地 PostgreSQL 預設不需要 |

---

## 設計原則

1. **最小依賴** — 核心只需 pydantic + litellm + chromadb
2. **可插拔** — LLM、Memory Store、Session Store、Guardrail、Tool Selector 都是介面，可替換實作
3. **per-user 記憶** — 所有操作以 user_id 為 scope，記憶自動提取和去重
4. **Stateless 部署** — Session Store 讓任何 instance 都能處理任何 request，不需 sticky session
5. **容錯優先** — Session/Memory 操作失敗時降級而非崩潰，stream 不會因基礎設施問題中斷
6. **Tool 就是函數** — `@tool` 裝飾器讓任何函數變成 agent 工具，sync/async 皆可
7. **Token 效率** — Prompt caching + 動態工具篩選，減少無謂的 token 開銷
8. **並行執行** — 多 tool calls 自動並行（sync: ThreadPoolExecutor, async: asyncio.gather）
