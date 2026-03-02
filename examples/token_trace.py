"""觀察多輪 tool calling 時 per-turn token 消耗的變化。

用法：
    python examples/token_trace.py

會自動送出多個需要 tool call 的問題，印出每輪 LLM call 的
prompt_tokens / completion_tokens，以及與前一輪的差值。
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from naru_agent import Agent, Runner, tool, EventBus
from naru_agent.llm import LiteLLMProvider

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
        results = list(FAKE_PRODUCTS.values())[:3]
    return "\n\n".join(results)


# --- Agent ---
agent = Agent(
    name="health_consultant",
    role="大醫生技健康產品顧問",
    goal="根據用戶需求推薦最適合的健康產品",
    system_prompt="""你是大醫生技的專業健康顧問。
規則：
- 使用 search_products 工具查詢產品
- 用繁體中文簡短回答""",
    llm=llm,
    tools=[search_products],
)

# --- Token tracking ---
turn_log: list[dict] = []
prev_prompt = 0


def on_before(d):
    print(f"  [LLM] 第 {d['iteration']+1} 輪開始 (messages: {d['message_count']})")


def on_after(d):
    global prev_prompt
    usage = d.get("usage", {})
    prompt = usage.get("prompt_tokens", 0)
    completion = usage.get("completion_tokens", 0)
    delta = prompt - prev_prompt if prev_prompt else 0
    delta_str = f" (Δ prompt: +{delta})" if prev_prompt else ""

    turn_log.append({
        "iteration": d["iteration"] + 1,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "delta_prompt": delta,
    })

    print(
        f"  [LLM] 第 {d['iteration']+1} 輪結束 — "
        f"prompt: {prompt}, completion: {completion}{delta_str}"
    )
    prev_prompt = prompt


def on_tool(d):
    print(f"  [Tool] {d['tool']} 回傳 {d['result_length']} 字")


bus = EventBus()
bus.on("before_llm_call", on_before)
bus.on("after_llm_call", on_after)
bus.on("after_tool_call", on_tool)

runner = Runner(agent, event_bus=bus)

# --- 自動送出多個問題 ---
QUESTIONS = [
    "推薦膝蓋保養的產品",
    "眼睛容易疲勞，有什麼推薦？",
    "最近消化不太好，有推薦的嗎？",
]

print("=" * 60)
print("Token Trace — 觀察多輪 tool calling 的 token 消耗")
print("=" * 60)

history: list[dict[str, str]] = []

for i, question in enumerate(QUESTIONS):
    prev_prompt = 0  # reset per question
    print(f"\n{'─' * 60}")
    print(f"Q{i+1}: {question}")
    print(f"{'─' * 60}")

    result = runner.run(
        message=question,
        conversation_history=history[-6:],
    )

    print(f"\nA: {result.content[:120]}{'...' if len(result.content) > 120 else ''}")
    if result.usage:
        print(f"  [total tokens: {result.usage.get('total_tokens', '?')}]")

    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": result.content})

# --- Summary ---
print(f"\n{'=' * 60}")
print("Summary")
print(f"{'=' * 60}")
print(f"{'輪次':<6} {'prompt':>8} {'completion':>11} {'Δ prompt':>10}")
print(f"{'─' * 37}")
for t in turn_log:
    delta_str = f"+{t['delta_prompt']}" if t['delta_prompt'] else "—"
    print(f"  {t['iteration']:<4} {t['prompt_tokens']:>8} {t['completion_tokens']:>11} {delta_str:>10}")
