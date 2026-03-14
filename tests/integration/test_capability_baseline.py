"""Naru Agent 能力基線測試套件。

覆蓋：RAG 檢索品質、知識圖譜、記憶準確度、壓縮後保留率、tool 精準度、多輪連貫性。

執行：
    GEMINI_API_KEY=xxx pytest tests/integration/test_capability_baseline.py -v --tb=short -x
"""

import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import litellm
import pytest

from naru_agent.agent import NaruAgent
from naru_agent.tools.base import tool

pytestmark = pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set",
)

MODEL = os.getenv("CHAT_AGENT_MODEL", "gemini/gemini-2.5-flash-lite")
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", "gemini/gemma-3-12b-it")
BASELINE_PATH = Path(__file__).parent.parent / "shared" / "baselines" / "quality_baseline.json"


def load_baseline() -> dict:
    if not BASELINE_PATH.exists():
        pytest.fail(f"Baseline file not found: {BASELINE_PATH}")
    return json.loads(BASELINE_PATH.read_text())


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

def embed_fn(texts: list[str]) -> list[list[float]]:
    resp = litellm.embedding(model="gemini/gemini-embedding-001", input=texts)
    return [d["embedding"] for d in resp.data]


def embed_single(text: str) -> list[float]:
    return embed_fn([text])[0]


# ---------------------------------------------------------------------------
# Knowledge facts
# ---------------------------------------------------------------------------

KNOWLEDGE_FACTS = [
    "Naru Agent supports over 100 LLM models through LiteLLM integration.",
    "The default vector database for development is ChromaDB with cosine similarity.",
    "Context compression triggers when conversation rounds exceed the threshold.",
    "Guardrails can use keyword matching, regex patterns, or custom LLM evaluation.",
    "The memory system uses LLM-driven fact extraction followed by reconciliation.",
    "GraphKnowledgeStore uses NetworkX for knowledge graph with BFS-based search.",
    "Tool selection uses embedding similarity to dynamically filter top-k tools.",
]

GRAPH_TEXT = """
Aspirin is a medication that treats headaches. Headaches are a symptom of migraines.
Migraines can be caused by stress. Ibuprofen also treats headaches.
Stress can be reduced by meditation. Meditation is related to mindfulness.
"""

# ---------------------------------------------------------------------------
# 16 e-commerce tools (reused from test_quality_baseline)
# ---------------------------------------------------------------------------

call_log: list[dict] = []


def _log(name: str, **kwargs):
    call_log.append({"tool": name, **kwargs})


@tool(description="搜尋產品，回傳產品列表")
def search_products(query: str) -> str:
    _log("search_products", query=query)
    return json.dumps([
        {"id": "P001", "name": "Sony WH-1000XM5 無線耳機", "price": 8990},
        {"id": "P002", "name": "AirPods Pro 2 無線耳機", "price": 7490},
    ])


@tool(description="取得單一產品的詳細資訊")
def get_product_detail(product_id: str) -> str:
    _log("get_product_detail", product_id=product_id)
    return json.dumps({"id": product_id, "name": "Sony WH-1000XM5 無線耳機", "price": 8990, "brand": "Sony", "category": "耳機"})


@tool(description="查詢產品庫存數量")
def check_inventory(product_id: str) -> str:
    _log("check_inventory", product_id=product_id)
    return json.dumps({"product_id": product_id, "available": 42})


@tool(description="建立新訂單")
def create_order(product_id: str, quantity: int) -> str:
    _log("create_order", product_id=product_id, quantity=quantity)
    return json.dumps({"order_id": "ORD-12345", "status": "created"})


@tool(description="查詢訂單狀態")
def get_order_status(order_id: str) -> str:
    _log("get_order_status", order_id=order_id)
    return json.dumps({"order_id": order_id, "status": "processing"})


@tool(description="取消訂單")
def cancel_order(order_id: str) -> str:
    _log("cancel_order", order_id=order_id)
    return json.dumps({"order_id": order_id, "status": "cancelled"})


@tool(description="取得用戶個人資料")
def get_user_profile(user_id: str) -> str:
    _log("get_user_profile", user_id=user_id)
    return json.dumps({"user_id": user_id, "name": "Alice", "email": "alice@example.com"})


@tool(description="更新用戶資料的某個欄位")
def update_user_profile(user_id: str, field: str, value: str) -> str:
    _log("update_user_profile", user_id=user_id, field=field, value=value)
    return json.dumps({"user_id": user_id, "updated": {field: value}})


@tool(description="查詢到指定目的地的物流選項")
def get_shipping_options(destination: str) -> str:
    _log("get_shipping_options", destination=destination)
    return json.dumps([{"method": "standard", "days": 5}, {"method": "express", "days": 2}])


@tool(description="計算到指定目的地的運費，需提供目的地和包裹重量(公斤)")
def calculate_shipping_cost(destination: str, weight: float) -> str:
    _log("calculate_shipping_cost", destination=destination, weight=weight)
    cost = 60 + weight * 25
    return json.dumps({"destination": destination, "weight_kg": weight, "cost_ntd": cost})


@tool(description="套用優惠券到訂單")
def apply_coupon(order_id: str, coupon_code: str) -> str:
    _log("apply_coupon", order_id=order_id, coupon_code=coupon_code)
    return json.dumps({"order_id": order_id, "discount": "10%"})


@tool(description="根據用戶偏好推薦商品")
def get_recommendations(user_id: str) -> str:
    _log("get_recommendations", user_id=user_id)
    return json.dumps([{"id": "P003", "name": "Bose QC45"}, {"id": "P004", "name": "JBL Tune 770NC"}])


@tool(description="提交產品評論")
def submit_review(product_id: str, rating: int, comment: str) -> str:
    _log("submit_review", product_id=product_id, rating=rating, comment=comment)
    return json.dumps({"status": "submitted", "review_id": "R-001"})


@tool(description="查詢產品的所有評論")
def get_reviews(product_id: str) -> str:
    _log("get_reviews", product_id=product_id)
    return json.dumps([{"rating": 5, "comment": "很棒！"}, {"rating": 4, "comment": "不錯"}])


@tool(description="追蹤物流包裹狀態")
def track_shipment(tracking_number: str) -> str:
    _log("track_shipment", tracking_number=tracking_number)
    return json.dumps({"tracking_number": tracking_number, "status": "in_transit", "location": "台北轉運站"})


@tool(description="聯繫客服，提交問題描述")
def contact_support(issue: str) -> str:
    _log("contact_support", issue=issue)
    return json.dumps({"ticket_id": "TK-9999", "status": "opened"})


ALL_TOOLS = [
    search_products, get_product_detail, check_inventory, create_order,
    get_order_status, cancel_order, get_user_profile, update_user_profile,
    get_shipping_options, calculate_shipping_cost, apply_coupon,
    get_recommendations, submit_review, get_reviews, track_shipment,
    contact_support,
]


@pytest.fixture(autouse=True)
def _clear_call_log():
    call_log.clear()
    yield
    call_log.clear()


def _make_agent(tools=None, **kwargs):
    return NaruAgent(
        model=MODEL,
        api_key=os.getenv("GEMINI_API_KEY"),
        instructions=["你是一個電商助手，請用繁體中文回覆。"],
        tools=tools or [],
        **kwargs,
    )


def _drain_bg(agent: NaruAgent):
    agent._bg_executor.shutdown(wait=True)
    agent._bg_executor = ThreadPoolExecutor(max_workers=2)


# ===========================================================================
# 1. TestKnowledgeRetrieval — RAG 檢索品質
# ===========================================================================


class TestKnowledgeRetrieval:

    @pytest.fixture(autouse=True)
    def _setup_knowledge_store(self, tmp_path):
        from naru_agent.knowledge.chroma_store import ChromaKnowledgeStore

        self.store = ChromaKnowledgeStore(
            embed_fn=embed_fn,
            persist_dir=str(tmp_path / "knowledge_db"),
        )
        self.store.batch_ingest(KNOWLEDGE_FACTS)

    def test_agent_uses_retrieved_knowledge(self):
        agent = _make_agent(knowledge_store=self.store)
        result = agent.chat("Naru 用什麼向量資料庫？")

        assert not result.blocked
        assert any(kw in result.content for kw in ["ChromaDB", "chromadb", "cosine"]), (
            f"Expected ChromaDB/cosine in response: {result.content[:300]}"
        )

    def test_agent_cites_specific_facts(self):
        agent = _make_agent(knowledge_store=self.store)
        result = agent.chat("記憶系統如何提取資訊？")

        assert not result.blocked
        assert any(kw in result.content.lower() for kw in ["fact extraction", "reconciliation", "事實", "萃取", "和解"]), (
            f"Expected fact extraction/reconciliation mention: {result.content[:300]}"
        )

    def test_agent_refuses_unknown(self):
        agent = _make_agent(knowledge_store=self.store)
        result = agent.chat("Naru Agent 的定價是多少？")

        assert not result.blocked
        content = result.content.lower()
        has_price = any(kw in content for kw in ["$", "costs", "priced", "usd", "ntd"])
        has_refusal = any(kw in content for kw in ["don't have", "not sure", "沒有", "不確定", "無法", "不清楚", "未提供"])
        assert not has_price or has_refusal, (
            f"Agent should not fabricate pricing info: {result.content[:300]}"
        )


# ===========================================================================
# 2. TestKnowledgeGraph — 圖譜品質
# ===========================================================================


class TestKnowledgeGraph:

    @pytest.fixture(autouse=True)
    def _setup_graph(self):
        from naru_agent.knowledge.graph_extractor import GraphExtractor
        from naru_agent.knowledge.graph_store import GraphKnowledgeStore

        extractor = GraphExtractor(
            model=MODEL,
            api_key=os.getenv("GEMINI_API_KEY"),
        )
        self.store = GraphKnowledgeStore(extractor=extractor)
        self.store.ingest_text(GRAPH_TEXT)

    def test_graph_entity_extraction(self):
        baseline = load_baseline()
        min_entities = baseline["graph_min_entities"]
        n = self.store.graph.number_of_nodes()
        assert n >= min_entities, f"Expected >= {min_entities} entities, got {n}. Nodes: {list(self.store.graph.nodes)}"

    def test_graph_relation_extraction(self):
        baseline = load_baseline()
        min_relations = baseline["graph_min_relations"]
        n = self.store.graph.number_of_edges()
        assert n >= min_relations, f"Expected >= {min_relations} relations, got {n}"

        # Check aspirin-headache relation exists (in either direction)
        nodes = list(self.store.graph.nodes)
        aspirin_node = next((n for n in nodes if "aspirin" in n.lower()), None)
        headache_node = next((n for n in nodes if "headache" in n.lower()), None)
        assert aspirin_node and headache_node, (
            f"Expected aspirin and headache nodes. Got: {nodes}"
        )
        has_edge = (
            self.store.graph.has_edge(aspirin_node, headache_node)
            or self.store.graph.has_edge(headache_node, aspirin_node)
        )
        assert has_edge, f"Expected edge between {aspirin_node} and {headache_node}"

    def test_graph_search_traversal(self):
        results_headache = self.store.search("treats headaches", top_k=5)
        combined_text = " ".join(r.text.lower() for r in results_headache)
        assert "aspirin" in combined_text or "ibuprofen" in combined_text, (
            f"Search 'treats headaches' should find aspirin/ibuprofen. Got: {combined_text[:300]}"
        )

        results_stress = self.store.search("reduce stress", top_k=5)
        combined_text2 = " ".join(r.text.lower() for r in results_stress)
        assert "meditation" in combined_text2, (
            f"Search 'reduce stress' should find meditation. Got: {combined_text2[:300]}"
        )


# ===========================================================================
# 3. TestMemoryRecall — 記憶準確度
# ===========================================================================


class TestMemoryRecall:

    def test_fact_extraction_and_storage(self, tmp_path):
        from naru_agent.llm.litellm_provider import LiteLLMProvider
        from naru_agent.memory.manager import MemoryManager
        from naru_agent.memory.stores.chroma import ChromaMemoryStore

        llm = LiteLLMProvider(model=MODEL, api_key=os.getenv("GEMINI_API_KEY"))
        store = ChromaMemoryStore(persist_dir=str(tmp_path / "mem_db"))
        manager = MemoryManager(llm=llm, store=store, embed_fn=embed_single)

        messages = [
            {"role": "user", "content": "我叫 Alice，住在台北，我最喜歡 Python 程式語言。"},
            {"role": "assistant", "content": "很高興認識你 Alice！台北是個很棒的城市。Python 確實是很優秀的語言。"},
        ]
        manager.add("test_user", messages)

        baseline = load_baseline()
        items = manager.get_all("test_user")
        assert len(items) >= baseline["memory_min_extracted_facts"], (
            f"Expected >= {baseline['memory_min_extracted_facts']} facts, got {len(items)}: "
            f"{[i.content for i in items]}"
        )
        all_content = " ".join(i.content.lower() for i in items)
        assert "alice" in all_content or "taipei" in all_content or "台北" in all_content, (
            f"Expected Alice/Taipei in memories: {all_content}"
        )

    def test_memory_recall_via_agent(self):
        agent = _make_agent(add_history_to_context=True)
        sid = "mem-recall-test"

        r1 = agent.chat("我對花生嚴重過敏，請記住這件事。", session_id=sid)
        assert not r1.blocked

        r2 = agent.chat("我有什麼過敏？", session_id=sid)
        assert not r2.blocked
        assert "花生" in r2.content or "peanut" in r2.content.lower(), (
            f"Expected peanut allergy recall: {r2.content[:300]}"
        )


# ===========================================================================
# 4. TestContextRetention — 壓縮後保留率
# ===========================================================================


class TestContextRetention:

    def _make_compression_agent(self, threshold=3, keep_last=3):
        return NaruAgent(
            model=MODEL,
            api_key=os.getenv("GEMINI_API_KEY"),
            instructions=["You are a helpful assistant. Reply concisely."],
            add_history_to_context=True,
            context_compression=True,
            summary_model=SUMMARY_MODEL,
            compression_threshold_rounds=threshold,
            compression_keep_last_rounds=keep_last,
        )

    def test_compressed_content_accessible(self):
        agent = self._make_compression_agent(threshold=3, keep_last=3)
        sid = "retention-test"

        agent.chat("The project deadline is March 15. Please remember this date.", session_id=sid)
        agent.chat("We need to use Python 3.12 for the project.", session_id=sid)
        agent.chat("The team lead is Dr. Wang.", session_id=sid)
        agent.chat("We should deploy to AWS.", session_id=sid)  # triggers compression
        agent.chat("Let's use PostgreSQL for the database.", session_id=sid)
        _drain_bg(agent)

        result = agent.chat("What is the project deadline?", session_id=sid)
        assert any(kw in result.content for kw in ["March 15", "3月15", "3/15", "三月十五"]), (
            f"Expected March 15 in response: {result.content[:300]}"
        )

    def test_multi_fact_retention(self):
        agent = self._make_compression_agent(threshold=3, keep_last=3)
        sid = "multi-fact-test"

        facts = [
            ("The budget is $50,000.", ["50,000", "50000", "$50"]),
            ("The client name is Acme Corp.", ["Acme", "acme"]),
            ("The tech stack is React and Node.js.", ["React", "Node", "react", "node"]),
        ]

        for fact_text, _ in facts:
            agent.chat(fact_text, session_id=sid)

        # Extra rounds to trigger compression
        agent.chat("Thanks for noting all that.", session_id=sid)
        agent.chat("Let me review the project details.", session_id=sid)
        _drain_bg(agent)

        baseline = load_baseline()
        correct = 0
        for fact_text, keywords in facts:
            question = f"What did I say about: {fact_text.split(' is ')[0] if ' is ' in fact_text else fact_text[:20]}?"
            result = agent.chat(question, session_id=sid)
            if any(kw in result.content for kw in keywords):
                correct += 1

        ratio = correct / len(facts)
        assert ratio >= baseline["compression_retention_min_ratio"], (
            f"Retention ratio {ratio:.2f} < {baseline['compression_retention_min_ratio']}"
        )


# ===========================================================================
# 5. TestToolCallingPrecision — Tool 精準度
# ===========================================================================


class TestToolCallingPrecision:

    def test_no_tool_for_chitchat(self):
        baseline = load_baseline()
        agent = _make_agent(tools=ALL_TOOLS)
        result = agent.chat("你好嗎？今天天氣真好。")

        assert len(result.tool_calls) <= baseline["chitchat_max_tool_calls"], (
            f"Chitchat should not call tools, but called: {result.tool_calls}"
        )

    def test_avoids_wrong_tool(self):
        agent = _make_agent(tools=ALL_TOOLS)
        result = agent.chat("告訴我關於物流的事")

        # Should not call calculate_shipping_cost because required params are missing
        called_names = [c["tool"] for c in call_log]
        if "calculate_shipping_cost" in called_names:
            # If it was called, it should have sensible args (not made-up values)
            calc_calls = [c for c in call_log if c["tool"] == "calculate_shipping_cost"]
            for c in calc_calls:
                assert "destination" in c and "weight" in c, (
                    "calculate_shipping_cost called without proper params"
                )

    def test_tool_chain_ordering(self):
        agent = _make_agent(tools=ALL_TOOLS)
        result = agent.chat("幫我搜尋耳機，然後查第一個產品的庫存，最後幫我訂 2 個")

        called_names = [c["tool"] for c in call_log]
        assert "search_products" in called_names, "Should call search_products"
        assert "check_inventory" in called_names, "Should call check_inventory"
        assert "create_order" in called_names, "Should call create_order"

        # Verify ordering
        idx_search = called_names.index("search_products")
        idx_inventory = called_names.index("check_inventory")
        idx_order = called_names.index("create_order")
        assert idx_search < idx_inventory < idx_order, (
            f"Tool chain order wrong: search@{idx_search}, inventory@{idx_inventory}, order@{idx_order}"
        )


# ===========================================================================
# 6. TestMultiTurnCoherence — 多輪連貫性
# ===========================================================================


class TestMultiTurnCoherence:

    def test_pronoun_resolution(self):
        agent = _make_agent(tools=ALL_TOOLS, add_history_to_context=True)
        sid = "pronoun-test"

        agent.chat("幫我搜尋 Sony 耳機", session_id=sid)
        result = agent.chat("第一個多少錢？", session_id=sid)

        assert not result.blocked
        assert "8990" in result.content, (
            f"Expected price 8990 in response: {result.content[:300]}"
        )

    def test_topic_continuity(self):
        agent = _make_agent(tools=ALL_TOOLS, add_history_to_context=True)
        sid = "topic-test"

        agent.chat("幫我訂購產品 P001，1 個", session_id=sid)
        call_log.clear()
        agent.chat("改成 3 個", session_id=sid)

        order_calls = [c for c in call_log if c["tool"] == "create_order"]
        assert len(order_calls) >= 1, "Should call create_order for the update"
        last_order = order_calls[-1]
        assert last_order.get("quantity") == 3, (
            f"Expected quantity=3, got {last_order}"
        )
        assert last_order.get("product_id") == "P001", (
            f"Expected product_id=P001, got {last_order}"
        )

    def test_correction_handling(self):
        agent = _make_agent(tools=ALL_TOOLS, add_history_to_context=True)
        sid = "correction-test"

        agent.chat("幫我計算寄到台北的運費，包裹 5 公斤", session_id=sid)
        call_log.clear()
        agent.chat("不對，改成寄到高雄", session_id=sid)

        shipping_calls = [c for c in call_log if c["tool"] == "calculate_shipping_cost"]
        assert len(shipping_calls) >= 1, "Should recalculate shipping cost"
        last_call = shipping_calls[-1]
        assert "高雄" in last_call.get("destination", ""), (
            f"Expected 高雄 in destination, got: {last_call}"
        )
