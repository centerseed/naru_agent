"""驗證 Tool Selection 的實際效果：token 節省 + 正確 function call。

測試策略：
- 用 json.dumps 估算 tool schema 的 token 開銷（1 token ≈ 4 chars）
- 透過 MockLLM.chat_calls 捕捉實際送出的 tools
- 驗證篩選後 LLM 仍能正確呼叫目標工具並取得結果
"""
from __future__ import annotations

import json

import pytest

from naru_agent.agent import Agent
from naru_agent.events import EventBus
from naru_agent.llm.base import LLMResponse
from naru_agent.runner import Runner
from naru_agent.tool_selection.embedding import EmbeddingToolSelector
from naru_agent.tools.base import BaseTool, tool
from tests.conftest import MockLLM


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _keyword_embed_fn(texts: list[str]) -> list[list[float]]:
    keywords = [
        "weather", "forecast", "temperature",
        "calendar", "schedule", "meeting",
        "search", "find", "query",
        "email", "send", "message",
        "calculate", "math", "number",
        "file", "read", "write",
        "translate", "language", "convert",
        "stock", "price", "market",
    ]
    results = []
    for text in texts:
        text_lower = text.lower()
        vec = [1.0 if kw in text_lower else 0.0 for kw in keywords]
        results.append(vec)
    return results


def _make_rich_tools() -> list[BaseTool]:
    """建立 15 個有豐富 description 和參數的工具，模擬真實場景。"""

    @tool(description="Get current weather forecast and temperature for a specific city. Returns detailed weather data including humidity, wind speed, and precipitation probability.")
    def get_weather(city: str, unit: str = "celsius") -> str:
        return f"Weather in {city}: 25°C, sunny"

    @tool(description="Get calendar schedule and meeting list for a date range. Supports filtering by attendee and meeting type.")
    def get_calendar(start_date: str, end_date: str = "", attendee: str = "") -> str:
        return f"Calendar for {start_date}: 3 meetings"

    @tool(description="Search the web and find relevant information using a natural language query. Supports filtering by date range and domain.")
    def web_search(query: str, max_results: int = 10, date_range: str = "") -> str:
        return f"Found 5 results for: {query}"

    @tool(description="Send an email message to a recipient with subject and body. Supports CC, BCC, and attachments.")
    def send_email(to: str, subject: str, body: str, cc: str = "", bcc: str = "") -> str:
        return f"Email sent to {to}"

    @tool(description="Calculate mathematical expressions with numbers. Supports arithmetic, trigonometry, and statistical functions.")
    def calculate(expression: str) -> str:
        return f"Result: 42"

    @tool(description="Read file contents from a given path. Supports text, JSON, CSV, and binary files with encoding options.")
    def read_file(path: str, encoding: str = "utf-8") -> str:
        return f"Contents of {path}"

    @tool(description="Write content to a file at the specified path. Creates directories if needed. Supports append mode.")
    def write_file(path: str, content: str, mode: str = "w") -> str:
        return f"Written to {path}"

    @tool(description="Translate text between languages using neural machine translation. Supports 100+ language pairs.")
    def translate_text(text: str, source_lang: str = "auto", target_lang: str = "en") -> str:
        return f"Translated: {text}"

    @tool(description="Get real-time stock price and market data for a ticker symbol. Includes open, close, high, low, and volume.")
    def get_stock_price(ticker: str, period: str = "1d") -> str:
        return f"Stock {ticker}: $150.00"

    @tool(description="Generate a summary of long documents into key bullet points. Configurable length and focus areas.")
    def summarize(text: str, max_points: int = 5, focus: str = "") -> str:
        return f"Summary: 5 key points"

    @tool(description="Create and manage database records. Supports CRUD operations with filtering and sorting.")
    def database_query(table: str, operation: str = "select", filters: str = "") -> str:
        return f"Query result: 10 rows"

    @tool(description="Generate images from text prompts using AI. Configurable size, style, and quality settings.")
    def generate_image(prompt: str, size: str = "1024x1024", style: str = "natural") -> str:
        return f"Image generated for: {prompt}"

    @tool(description="Manage user authentication and sessions. Supports login, logout, token refresh, and permission checks.")
    def auth_manager(action: str, username: str = "", token: str = "") -> str:
        return f"Auth action: {action}"

    @tool(description="Send notifications through multiple channels: push, SMS, email, and in-app. Supports scheduling.")
    def send_notification(channel: str, message: str, recipient: str, schedule: str = "") -> str:
        return f"Notification sent via {channel}"

    @tool(description="Analyze data and generate charts with statistical insights. Supports bar, line, pie, and scatter plots.")
    def data_analysis(dataset: str, chart_type: str = "bar", metrics: str = "") -> str:
        return f"Analysis complete for {dataset}"

    return [
        get_weather, get_calendar, web_search, send_email, calculate,
        read_file, write_file, translate_text, get_stock_price, summarize,
        database_query, generate_image, auth_manager, send_notification,
        data_analysis,
    ]


def _estimate_tokens(tools_schema: list[dict]) -> int:
    """粗估 tool schema 的 token 數（1 token ≈ 4 chars）。"""
    return len(json.dumps(tools_schema, ensure_ascii=False)) // 4


def _make_agent(mock_llm: MockLLM, tools: list[BaseTool]) -> Agent:
    return Agent(name="Test", role="assistant", llm=mock_llm, tools=tools)


# ===========================================================================
# A. Token 節省驗證
# ===========================================================================


class TestTokenReduction:
    """驗證 tool selection 顯著減少送給 LLM 的 schema tokens。"""

    def test_schema_token_reduction_at_least_50_percent(self, mock_llm):
        """15 個工具篩選到 top_k=3，schema tokens 應減少 ≥50%。"""
        tools = _make_rich_tools()
        mock_llm.set_response("It's sunny today.")
        agent = _make_agent(mock_llm, tools)

        # 無篩選
        runner_no_filter = Runner(agent)
        runner_no_filter.run("What's the weather in Tokyo?")
        all_tools_schema = mock_llm.chat_calls[0]["tools"]
        tokens_no_filter = _estimate_tokens(all_tools_schema)

        # 有篩選
        mock_llm.chat_calls.clear()
        mock_llm.set_response("It's sunny today.")
        selector = EmbeddingToolSelector(
            embed_fn=_keyword_embed_fn, top_k=3, min_tools_to_filter=5,
        )
        runner_filtered = Runner(agent, tool_selector=selector)
        runner_filtered.run("What's the weather in Tokyo?")
        filtered_tools_schema = mock_llm.chat_calls[0]["tools"]
        tokens_filtered = _estimate_tokens(filtered_tools_schema)

        reduction = 1 - (tokens_filtered / tokens_no_filter)
        assert reduction >= 0.50, (
            f"Token reduction {reduction:.0%} < 50%. "
            f"No filter: {tokens_no_filter} tokens, filtered: {tokens_filtered} tokens"
        )
        assert len(filtered_tools_schema) <= 3
        assert len(all_tools_schema) == 15

    def test_schema_token_count_scales_with_top_k(self, mock_llm):
        """top_k 越小，送出的 schema tokens 越少。"""
        tools = _make_rich_tools()
        agent = _make_agent(mock_llm, tools)
        token_counts = {}

        for k in [2, 5, 10]:
            mock_llm.chat_calls.clear()
            mock_llm.set_response("Done.")
            selector = EmbeddingToolSelector(
                embed_fn=_keyword_embed_fn, top_k=k, min_tools_to_filter=5,
            )
            Runner(agent, tool_selector=selector).run("weather forecast")
            schema = mock_llm.chat_calls[0]["tools"]
            token_counts[k] = _estimate_tokens(schema)

        assert token_counts[2] < token_counts[5] < token_counts[10]

    def test_multi_iteration_all_calls_use_filtered_tools(self, mock_llm):
        """多輪迭代中，每次 LLM 呼叫都用篩選後的工具集（而非全部）。"""
        tools = _make_rich_tools()
        mock_llm.queue_responses([
            LLMResponse(
                tool_calls=[{"id": "tc1", "name": "get_weather", "arguments": {"city": "Tokyo"}}],
                usage={"prompt_tokens": 100, "completion_tokens": 20},
            ),
            LLMResponse(
                content="Tokyo is 25°C and sunny.",
                usage={"prompt_tokens": 120, "completion_tokens": 30},
            ),
        ])
        agent = _make_agent(mock_llm, tools)
        selector = EmbeddingToolSelector(
            embed_fn=_keyword_embed_fn, top_k=3, min_tools_to_filter=5,
        )
        Runner(agent, tool_selector=selector).run("What's the weather?")

        # 兩次 LLM 呼叫都應該用篩選後的工具集
        assert len(mock_llm.chat_calls) == 2
        for call in mock_llm.chat_calls:
            assert len(call["tools"]) <= 5  # top_k=3 + used tools
            assert len(call["tools"]) < 15  # 遠小於全部


# ===========================================================================
# B. 正確 Function Call 驗證
# ===========================================================================


class TestCorrectFunctionCall:
    """驗證篩選後 LLM 仍能呼叫正確工具，且工具確實執行並回傳結果。"""

    def test_weather_tool_called_and_executed(self, mock_llm):
        """查詢天氣 → get_weather 被選中 → 工具執行 → 結果正確。"""
        tools = _make_rich_tools()
        mock_llm.queue_responses([
            LLMResponse(
                tool_calls=[{"id": "tc1", "name": "get_weather", "arguments": {"city": "Taipei"}}],
                usage={"prompt_tokens": 50, "completion_tokens": 10},
            ),
            LLMResponse(
                content="Taipei is 25°C and sunny.",
                usage={"prompt_tokens": 60, "completion_tokens": 15},
            ),
        ])
        agent = _make_agent(mock_llm, tools)
        selector = EmbeddingToolSelector(
            embed_fn=_keyword_embed_fn, top_k=3, min_tools_to_filter=5,
        )
        result = Runner(agent, tool_selector=selector).run(
            "What's the weather in Taipei?"
        )

        # 最終回應正確
        assert result.content == "Taipei is 25°C and sunny."
        # get_weather 在篩選集中
        first_call_tools = mock_llm.chat_calls[0]["tools"]
        tool_names = {t["function"]["name"] for t in first_call_tools}
        assert "get_weather" in tool_names
        # 工具回傳值出現在 messages 中
        second_call_msgs = mock_llm.chat_calls[1]["messages"]
        tool_result_msgs = [m for m in second_call_msgs if m.get("role") == "tool"]
        assert len(tool_result_msgs) == 1
        assert "Weather in Taipei: 25°C, sunny" in tool_result_msgs[0]["content"]

    def test_email_tool_called_and_executed(self, mock_llm):
        """寄信 → send_email 被選中 → 工具執行 → 結果正確。"""
        tools = _make_rich_tools()
        mock_llm.queue_responses([
            LLMResponse(
                tool_calls=[{
                    "id": "tc1", "name": "send_email",
                    "arguments": {"to": "boss@co.com", "subject": "Report", "body": "Q4 done"},
                }],
                usage={"prompt_tokens": 50, "completion_tokens": 10},
            ),
            LLMResponse(
                content="Email sent successfully.",
                usage={"prompt_tokens": 60, "completion_tokens": 10},
            ),
        ])
        agent = _make_agent(mock_llm, tools)
        selector = EmbeddingToolSelector(
            embed_fn=_keyword_embed_fn, top_k=3, min_tools_to_filter=5,
        )
        result = Runner(agent, tool_selector=selector).run(
            "Send an email message to boss@co.com about Q4 report"
        )

        assert result.content == "Email sent successfully."
        first_call_tools = mock_llm.chat_calls[0]["tools"]
        tool_names = {t["function"]["name"] for t in first_call_tools}
        assert "send_email" in tool_names
        # 工具確實執行
        tool_msgs = [m for m in mock_llm.chat_calls[1]["messages"] if m.get("role") == "tool"]
        assert "Email sent to boss@co.com" in tool_msgs[0]["content"]

    def test_calculate_tool_called_and_executed(self, mock_llm):
        """計算 → calculate 被選中 → 工具執行。"""
        tools = _make_rich_tools()
        mock_llm.queue_responses([
            LLMResponse(
                tool_calls=[{"id": "tc1", "name": "calculate", "arguments": {"expression": "17*23"}}],
                usage={"prompt_tokens": 50, "completion_tokens": 10},
            ),
            LLMResponse(
                content="17 * 23 = 391",
                usage={"prompt_tokens": 60, "completion_tokens": 10},
            ),
        ])
        agent = _make_agent(mock_llm, tools)
        selector = EmbeddingToolSelector(
            embed_fn=_keyword_embed_fn, top_k=3, min_tools_to_filter=5,
        )
        result = Runner(agent, tool_selector=selector).run(
            "Calculate the math: what is the number 17 times 23?"
        )

        assert result.content == "17 * 23 = 391"
        tool_names = {t["function"]["name"] for t in mock_llm.chat_calls[0]["tools"]}
        assert "calculate" in tool_names

    def test_chained_tool_calls_both_tools_available(self, mock_llm):
        """多步驟：先查天氣再寄信 → 兩個工具都在篩選集中。"""
        tools = _make_rich_tools()
        mock_llm.queue_responses([
            # Step 1: 查天氣
            LLMResponse(
                tool_calls=[{"id": "tc1", "name": "get_weather", "arguments": {"city": "Tokyo"}}],
                usage={"prompt_tokens": 50, "completion_tokens": 10},
            ),
            # Step 2: 寄信（get_weather 已被使用，必須保留在篩選集中）
            LLMResponse(
                tool_calls=[{
                    "id": "tc2", "name": "send_email",
                    "arguments": {"to": "team@co.com", "subject": "Weather", "body": "Tokyo sunny"},
                }],
                usage={"prompt_tokens": 80, "completion_tokens": 15},
            ),
            # Step 3: 完成
            LLMResponse(
                content="Done! Checked weather and sent the email.",
                usage={"prompt_tokens": 100, "completion_tokens": 20},
            ),
        ])
        agent = _make_agent(mock_llm, tools)
        selector = EmbeddingToolSelector(
            embed_fn=_keyword_embed_fn, top_k=3, min_tools_to_filter=5,
        )
        bus = EventBus()
        events = []
        bus.on("tool_selection", lambda d: events.append(d))

        result = Runner(agent, event_bus=bus, tool_selector=selector).run(
            "Check weather in Tokyo and send email to team"
        )

        assert result.content == "Done! Checked weather and sent the email."
        assert len(mock_llm.chat_calls) == 3

        # 第二輪篩選結果應包含 get_weather（used_tool_names 機制）
        assert len(events) == 3
        assert "get_weather" in events[1]["selected_names"]

        # 三次呼叫都用篩選後工具集
        for call in mock_llm.chat_calls:
            assert len(call["tools"]) < 15

    def test_tool_result_propagates_to_llm_context(self, mock_llm):
        """工具執行結果正確傳回 LLM 的 messages context。"""
        tools = _make_rich_tools()
        mock_llm.queue_responses([
            LLMResponse(
                tool_calls=[{
                    "id": "tc1", "name": "get_stock_price",
                    "arguments": {"ticker": "AAPL"},
                }],
                usage={"prompt_tokens": 50, "completion_tokens": 10},
            ),
            LLMResponse(
                content="AAPL is at $150.",
                usage={"prompt_tokens": 80, "completion_tokens": 10},
            ),
        ])
        agent = _make_agent(mock_llm, tools)
        selector = EmbeddingToolSelector(
            embed_fn=_keyword_embed_fn, top_k=3, min_tools_to_filter=5,
        )
        Runner(agent, tool_selector=selector).run(
            "What's the stock price of AAPL?"
        )

        # 第二次呼叫的 messages 應包含工具結果
        msgs = mock_llm.chat_calls[1]["messages"]
        tool_msg = next(m for m in msgs if m.get("role") == "tool")
        assert tool_msg["tool_call_id"] == "tc1"
        assert "Stock AAPL: $150.00" in tool_msg["content"]

    def test_irrelevant_tools_excluded_from_selection(self, mock_llm):
        """查天氣時，不相關的工具（如 generate_image）不應出現。"""
        tools = _make_rich_tools()
        mock_llm.set_response("Sunny!")
        agent = _make_agent(mock_llm, tools)
        selector = EmbeddingToolSelector(
            embed_fn=_keyword_embed_fn, top_k=3, min_tools_to_filter=5,
        )
        Runner(agent, tool_selector=selector).run("weather forecast temperature")

        tool_names = {t["function"]["name"] for t in mock_llm.chat_calls[0]["tools"]}
        # 天氣相關工具應被選中
        assert "get_weather" in tool_names
        # 明顯不相關的工具不應出現
        assert "generate_image" not in tool_names
        assert "auth_manager" not in tool_names
        assert "data_analysis" not in tool_names
