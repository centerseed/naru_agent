# naru_agent

輕量、可插拔的 Python agent 框架，支援 per-user 記憶、tool calling、guardrails。設計為 git submodule 嵌入各專案使用。

## 架構

```
naru_agent/
├── agent.py              # Agent 定義
├── runner.py             # ReAct 執行引擎
├── events.py             # 輕量事件匯流排
├── llm/
│   ├── base.py           # LLM 抽象介面
│   └── litellm_provider.py  # LiteLLM 實作（100+ models）
├── memory/
│   ├── base.py           # MemoryStore 介面
│   ├── manager.py        # LLM 驅動的事實提取 + 和解
│   ├── prompts.py        # 記憶用 prompt templates
│   └── stores/
│       └── chroma.py     # ChromaDB 後端
├── tools/
│   ├── base.py           # BaseTool + @tool 裝飾器
│   └── builtin/
│       └── rag.py        # 通用 RAG 查詢工具
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

## 事件監聽

```python
from naru_agent import EventBus

bus = EventBus()

# 監控 token 使用量
bus.on("after_llm_call", lambda data: print(f"LLM call #{data['iteration']}"))
bus.on("after_tool_call", lambda data: print(f"Tool: {data['tool']}"))

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

## 設計原則

1. **最小依賴** — 核心只需 pydantic + litellm + chromadb
2. **可插拔** — LLM、Memory Store、Guardrail 都是介面，可替換實作
3. **per-user 記憶** — 所有操作以 user_id 為 scope，記憶自動提取和去重
4. **不過度設計** — 沒有 Flow、沒有多 Agent 編排（需要時再加）
5. **Tool 就是函數** — `@tool` 裝飾器讓任何函數變成 agent 工具
