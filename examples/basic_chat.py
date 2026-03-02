"""基本測試：Agent + Tool + Memory + Guardrail 全流程"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from naru_agent import Agent, Runner, tool, MemoryManager, EventBus
from naru_agent.llm import LiteLLMProvider
from naru_agent.guardrails import KeywordGuardrail
from naru_agent.memory.stores.chroma import ChromaMemoryStore

# --- LLM ---
llm = LiteLLMProvider(model="gemini/gemini-2.5-flash-lite")

# --- Tools ---
FAKE_PRODUCTS = {
    "鈣片": "大醫生技海藻鈣 - NT$890 - 含維生素D3幫助吸收，適合骨質保養。每日2粒，每粒含300mg鈣。",
    "魚油": "大醫生技深海魚油 - NT$750 - EPA+DHA高濃度，支持心血管和關節健康。每日1-2粒。",
    "葉黃素": "大醫生技金盞花葉黃素 - NT$680 - 含游離型葉黃素+玉米黃素，適合長時間使用3C的族群。",
    "益生菌": "大醫生技活力益生菌 - NT$560 - 含8種專利菌株，幫助消化道機能。",
    "膠原蛋白": "大醫生技膠原蛋白胜肽 - NT$980 - 小分子好吸收，添加維生素C促進合成。",
    "薑黃": "大醫生技薑黃素 - NT$620 - 95%高濃度薑黃素，幫助維持關節靈活。",
}


@tool(description="搜索健康產品資料庫，回傳最相關的產品資訊")
def search_products(query: str) -> str:
    results = []
    for name, info in FAKE_PRODUCTS.items():
        if name in query or any(kw in query for kw in ["關節", "骨", "膝蓋"] if name in ["鈣片", "薑黃"]):
            results.append(info)
        elif any(kw in query for kw in ["眼睛", "視力", "3C"]) and name == "葉黃素":
            results.append(info)
        elif any(kw in query for kw in ["腸胃", "消化", "拉肚子"]) and name == "益生菌":
            results.append(info)
        elif any(kw in query for kw in ["皮膚", "美容"]) and name == "膠原蛋白":
            results.append(info)
        elif any(kw in query for kw in ["心血管", "血脂"]) and name == "魚油":
            results.append(info)
    if not results:
        # fallback: return all
        results = list(FAKE_PRODUCTS.values())[:3]
    return "\n\n".join(results)


# --- Guardrail ---
medical_guard = KeywordGuardrail(
    blocked_patterns=[r"處方", r"劑量", r"診斷", r"停藥", r"替代.*藥物"],
    input_message="我是健康產品顧問，無法提供醫療建議。建議您諮詢專業醫療人員。",
    output_replacement="（此部分涉及醫療建議，建議您諮詢專業醫療人員。）",
)

# --- Memory ---
embed_cache: dict[str, list[float]] = {}


def embed(text: str) -> list[float]:
    if text in embed_cache:
        return embed_cache[text]
    import google.genai as genai

    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    result = client.models.embed_content(
        model="gemini-embedding-001", contents=text
    )
    vec = list(result.embeddings[0].values)
    embed_cache[text] = vec
    return vec


memory = MemoryManager(
    llm=llm,
    store=ChromaMemoryStore(persist_dir="./examples/test_memory_db"),
    embed_fn=embed,
)

# --- Agent ---
agent = Agent(
    name="health_consultant",
    role="大醫生技健康產品顧問",
    goal="根據用戶需求推薦最適合的健康產品",
    system_prompt="""你是大醫生技的專業健康顧問，像朋友一樣親切地為用戶推薦產品。
規則：
- 只根據產品資料庫中的資訊回答，使用 search_products 工具查詢
- 不主動報價，除非用戶詢問
- 絕不提供醫療診斷或處方建議
- 找不到資料時誠實說需要確認
- 用繁體中文回答""",
    llm=llm,
    tools=[search_products],
    memory=memory,
    guardrails=[medical_guard],
)

# --- Event Bus ---
bus = EventBus()
bus.on("before_llm_call", lambda d: print(f"  [LLM] 第 {d['iteration']+1} 次呼叫開始 (messages: {d['message_count']})"))
bus.on("after_llm_call", lambda d: print(
    f"  [LLM] 第 {d['iteration']+1} 次呼叫 — "
    f"prompt: {d.get('usage', {}).get('prompt_tokens', '?')}, "
    f"completion: {d.get('usage', {}).get('completion_tokens', '?')}"
))
bus.on("after_tool_call", lambda d: print(f"  [Tool] {d['tool']} 回傳 {d['result_length']} 字"))

# --- 互動測試 ---
runner = Runner(agent, event_bus=bus)

print("=" * 60)
print("naru_agent 測試 — 健康產品顧問")
print("輸入 'quit' 結束, 'memory' 查看記憶")
print("=" * 60)

USER_ID = "test_user"
history: list[dict[str, str]] = []

while True:
    try:
        msg = input("\n你: ").strip()
    except (EOFError, KeyboardInterrupt):
        break

    if not msg:
        continue
    if msg.lower() == "quit":
        break
    if msg.lower() == "memory":
        memories = memory.get_all(USER_ID)
        if memories:
            print("\n📝 目前記憶：")
            for m in memories:
                print(f"  - {m.content}")
        else:
            print("\n（尚無記憶）")
        continue

    result = runner.run(
        message=msg,
        user_id=USER_ID,
        conversation_history=history[-6:],  # 保留最近3輪
    )

    if result.blocked:
        print(f"\n🚫 {result.content}")
    else:
        print(f"\n顧問: {result.content}")

    history.append({"role": "user", "content": msg})
    history.append({"role": "assistant", "content": result.content})

    if result.usage:
        tokens = result.usage.get("total_tokens", "?")
        print(f"  [tokens: {tokens}]")
