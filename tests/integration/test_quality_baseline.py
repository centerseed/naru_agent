"""NaruAgent 品質保證 Baseline 測試套件。

覆蓋：大量 tools 正確呼叫、多用戶並發、token 用量合理性、回應品質、trace 完整性。

執行：
    GEMINI_API_KEY=xxx pytest tests/integration/test_quality_baseline.py -v --tb=short -x
"""

import json
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from naru_agent.agent import NaruAgent
from naru_agent.intent.llm_classifier import LLMIntentClassifier
from naru_agent.tools.base import tool
from naru_agent.tracing.exporters.jsonl import JSONLTraceExporter

pytestmark = pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set",
)

MODEL = os.getenv("CHAT_AGENT_MODEL", "gemini/gemini-2.5-flash-lite")
BASELINE_PATH = Path(__file__).parent / "baselines" / "quality_baseline.json"


def load_baseline() -> dict:
    """載入 baseline 閾值。檔案必須存在，否則測試直接失敗。"""
    if not BASELINE_PATH.exists():
        pytest.fail(
            f"Baseline file not found: {BASELINE_PATH}\n"
            "This file defines quality thresholds and must be committed to the repo."
        )
    return json.loads(BASELINE_PATH.read_text())


# ---------------------------------------------------------------------------
# 16 個 @tool 函數
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


def _make_agent(tools=None, trace_file=None, intent_classifier=None, **kwargs):
    extra = {}
    if trace_file:
        extra["trace_exporters"] = [JSONLTraceExporter(trace_file)]
    if intent_classifier:
        extra["intent_classifier"] = intent_classifier
    return NaruAgent(
        model=MODEL,
        api_key=os.getenv("GEMINI_API_KEY"),
        instructions=["你是一個電商助手，請用繁體中文回覆。"],
        tools=tools or [],
        **extra,
        **kwargs,
    )


# ===========================================================================
# 1. TestManyTools — 大量 Tools 正確呼叫
# ===========================================================================


class TestManyTools:

    def test_agent_selects_correct_tool_from_16(self):
        agent = _make_agent(tools=ALL_TOOLS)
        result = agent.chat("請幫我計算寄到台北的運費，包裹重量 2 公斤")

        assert not result.blocked
        assert result.content
        assert "calculate_shipping_cost" in result.tool_calls
        called_names = [c["tool"] for c in call_log]
        assert "calculate_shipping_cost" in called_names

    def test_agent_chains_multiple_tools(self):
        agent = _make_agent(tools=ALL_TOOLS)
        result = agent.chat("幫我搜尋無線耳機，然後查看第一個產品的詳情和庫存")

        assert not result.blocked
        called_names = [c["tool"] for c in call_log]
        assert "search_products" in called_names
        assert "get_product_detail" in called_names or "check_inventory" in called_names
        # search_products should be called before get_product_detail
        if "get_product_detail" in called_names:
            assert called_names.index("search_products") < called_names.index("get_product_detail")

    def test_agent_response_quality_with_many_tools(self):
        agent = _make_agent(tools=ALL_TOOLS)
        result = agent.chat("請幫我計算寄到台北的運費，包裹重量 2 公斤")

        assert not result.blocked
        assert len(result.tool_calls) > 0, "Expected at least one tool call"
        # Response should contain cost info from the tool (cost = 60 + 2*25 = 110)
        assert any(kw in result.content for kw in ["110", "運費", "費用", "cost", "元"])


# ===========================================================================
# 2. TestConcurrency — 多用戶並發
# ===========================================================================


class TestConcurrency:

    def test_concurrent_different_users(self):
        agent = _make_agent(tools=ALL_TOOLS)

        requests = [
            ("user_1", "sess_1", "請幫我計算寄到台北的運費，包裹重量 3 公斤"),
            ("user_2", "sess_2", "幫我搜尋藍牙耳機"),
            ("user_3", "sess_3", "查詢訂單 ORD-100 的狀態"),
        ]

        results = {}
        exceptions = {}

        def _run(user_id, session_id, msg):
            return agent.chat(msg, user_id=user_id, session_id=session_id)

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                pool.submit(_run, uid, sid, msg): uid
                for uid, sid, msg in requests
            }
            for f in as_completed(futures):
                uid = futures[f]
                try:
                    results[uid] = f.result()
                except Exception as e:
                    exceptions[uid] = e

        assert not exceptions, f"Exceptions occurred: {exceptions}"
        for uid, r in results.items():
            assert not r.blocked, f"{uid} was blocked"
            assert r.content, f"{uid} got empty content"

    def test_concurrent_same_session_serialized(self):
        agent = _make_agent(tools=ALL_TOOLS, add_history_to_context=True)
        sid = "shared-session-serial"

        r1 = agent.chat("我叫做小明，請記住我的名字。", user_id="u1", session_id=sid)
        assert not r1.blocked

        r2 = agent.chat("我叫什麼名字？", user_id="u1", session_id=sid)
        assert not r2.blocked
        assert "小明" in r2.content


# ===========================================================================
# 3. TestTokenUsage — Token 用量合理性
# ===========================================================================


class TestTokenUsage:

    def test_simple_chat_token_budget(self):
        baseline = load_baseline()
        max_tokens = baseline["simple_chat_max_tokens"]

        agent = _make_agent()
        result = agent.chat("你好")

        total = result.usage.get("total", 0)
        assert total > 0, "usage.total should be > 0"
        assert total <= max_tokens, (
            f"Simple chat used {total} tokens, exceeds baseline max {max_tokens}. "
            "If this is expected, update baselines/quality_baseline.json manually."
        )

    def test_tool_call_token_budget(self):
        baseline = load_baseline()
        max_tokens = baseline["tool_call_16_tools_max_tokens"]

        agent = _make_agent(tools=ALL_TOOLS)
        result = agent.chat("請幫我計算寄到台北的運費，包裹重量 2 公斤")

        total = result.usage.get("total", 0)
        assert total > 0
        assert total <= max_tokens, (
            f"Tool call (16 tools) used {total} tokens, exceeds baseline max {max_tokens}. "
            "If this is expected, update baselines/quality_baseline.json manually."
        )

    def test_token_usage_fields_present(self):
        agent = _make_agent()
        result = agent.chat("你好")

        for field in ("input", "output", "total"):
            assert field in result.usage, f"usage missing '{field}'"
            assert result.usage[field] > 0, f"usage.{field} should be > 0"


# ===========================================================================
# 4. TestResponseQuality — 回應品質
# ===========================================================================


class TestResponseQuality:

    def test_response_contains_tool_result(self):
        agent = _make_agent(tools=ALL_TOOLS)
        result = agent.chat("追蹤包裹 TRK-ABC123")

        assert not result.blocked
        assert "track_shipment" in result.tool_calls
        # Tool returns "台北轉運站" and "in_transit"
        assert any(kw in result.content for kw in ["台北", "轉運", "transit", "TRK"])

    def test_response_language_follows_instruction(self):
        agent = _make_agent()
        result = agent.chat("Please introduce yourself and explain what you can help with.")

        assert not result.blocked
        # Instructions say 繁體中文, response should contain Chinese characters
        has_chinese = bool(re.search(r"[\u4e00-\u9fff]", result.content))
        assert has_chinese, f"Expected Chinese in response: {result.content[:200]}"

    def test_response_not_hallucinate_tool(self):
        agent = _make_agent(tools=ALL_TOOLS)
        result = agent.chat("請幫我計算寄到台北的運費，包裹重量 2 公斤")

        valid_names = {t.name for t in ALL_TOOLS}
        for tc in result.tool_calls:
            assert tc in valid_names, f"Hallucinated tool: {tc}"


# ===========================================================================
# 5. TestTraceCompleteness — Trace 完整性
# ===========================================================================


class TestTraceCompleteness:

    def _make_trace_agent(self, trace_file, **kwargs):
        return _make_agent(trace_file=trace_file, **kwargs)

    def _read_traces(self, trace_file, wait=0.5):
        time.sleep(wait)
        lines = Path(trace_file).read_text().strip().splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def test_trace_has_all_required_fields(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            trace_file = f.name

        agent = self._make_trace_agent(trace_file, tools=ALL_TOOLS)
        result = agent.chat("請幫我計算寄到台北的運費，包裹重量 1 公斤")

        traces = self._read_traces(trace_file)
        assert len(traces) >= 1

        t = traces[0]
        for field in ("trace_id", "input", "output", "start_time", "end_time", "usage", "spans"):
            assert field in t, f"Trace missing field: {field}"
        assert t["trace_id"] == result.trace_id

    def test_trace_spans_cover_llm_and_tools(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            trace_file = f.name

        agent = self._make_trace_agent(trace_file, tools=ALL_TOOLS)
        agent.chat("請幫我計算寄到台北的運費，包裹重量 1 公斤")

        traces = self._read_traces(trace_file)
        t = traces[0]
        span_names = [s.get("name", "") for s in t["spans"]]

        assert any("llm" in sn for sn in span_names), f"No llm span found in: {span_names}"
        # tool_call span may be separate or embedded; check spans or metadata
        has_tool_span = any("tool" in sn for sn in span_names)
        has_tool_in_meta = any(
            s.get("metadata", {}).get("has_tool_calls") for s in t["spans"]
        )
        assert has_tool_span or has_tool_in_meta, f"No tool evidence in spans: {span_names}"

    def test_trace_timing_consistency(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            trace_file = f.name

        agent = self._make_trace_agent(trace_file, tools=ALL_TOOLS)
        agent.chat("查詢訂單 ORD-100 的狀態")

        traces = self._read_traces(trace_file)
        t = traces[0]
        trace_start = t["start_time"]
        trace_end = t["end_time"]

        for span in t["spans"]:
            s_start = span.get("start_time", 0)
            s_end = span.get("end_time", float("inf"))
            assert s_start >= trace_start - 0.01, (
                f"Span start {s_start} < trace start {trace_start}"
            )
            assert s_end <= trace_end + 0.01, (
                f"Span end {s_end} > trace end {trace_end}"
            )

    def test_trace_with_intent_classifier(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            trace_file = f.name

        classifier = LLMIntentClassifier(
            model=MODEL,
            api_key=os.getenv("GEMINI_API_KEY"),
        )
        agent = self._make_trace_agent(
            trace_file, tools=ALL_TOOLS, intent_classifier=classifier,
        )
        agent.chat("請幫我計算寄到台北的運費，包裹重量 1 公斤")

        traces = self._read_traces(trace_file)
        t = traces[0]
        span_names = [s.get("name", "") for s in t["spans"]]
        assert any("intent" in sn for sn in span_names), (
            f"No intent span found in: {span_names}"
        )

    def test_trace_jsonl_parseable(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            trace_file = f.name

        agent = self._make_trace_agent(trace_file)
        agent.chat("你好")

        time.sleep(0.5)
        raw_lines = Path(trace_file).read_text().strip().splitlines()
        assert len(raw_lines) >= 1

        for i, line in enumerate(raw_lines):
            try:
                json.loads(line)
            except json.JSONDecodeError as e:
                pytest.fail(f"Line {i} is not valid JSON: {e}\n{line[:200]}")
