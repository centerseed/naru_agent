"""Tool selection 單元測試（使用 keyword-based mock embed_fn）"""
from __future__ import annotations

import pytest

from naru_agent.agent import Agent
from naru_agent.events import EventBus
from naru_agent.llm.base import LLMResponse
from naru_agent.runner import Runner
from naru_agent.tool_selection.base import BaseToolSelector, ToolSelectionResult
from naru_agent.tool_selection.embedding import EmbeddingToolSelector, _tool_to_text
from naru_agent.tools.base import BaseTool, tool
from tests.conftest import MockLLM


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _keyword_embed_fn(texts: list[str]) -> list[list[float]]:
    """Keyword-based mock embedding: each dimension maps to a keyword."""
    keywords = [
        "weather", "forecast", "temperature",
        "calendar", "schedule", "meeting",
        "search", "find", "query",
        "email", "send", "message",
        "calculate", "math", "number",
        "file", "read", "write",
    ]
    results = []
    for text in texts:
        text_lower = text.lower()
        vec = [1.0 if kw in text_lower else 0.0 for kw in keywords]
        results.append(vec)
    return results


def _make_tools(n: int) -> list[BaseTool]:
    """Create n distinct tools with keyword-rich descriptions."""
    tool_defs = [
        ("get_weather", "Get weather forecast and temperature for a city"),
        ("get_calendar", "Get calendar schedule and meeting list"),
        ("web_search", "Search and find information using a query"),
        ("send_email", "Send an email message to a recipient"),
        ("calculate", "Calculate math expressions with numbers"),
        ("read_file", "Read and write file contents"),
        ("translate", "Translate text between languages"),
        ("summarize", "Summarize long documents into key points"),
        ("generate_image", "Generate an image from a text prompt"),
        ("play_music", "Play music tracks and playlists"),
        ("get_news", "Get latest news articles"),
        ("set_reminder", "Set a reminder for a future time"),
        ("convert_currency", "Convert currency between countries"),
        ("get_stock_price", "Get stock price and market data"),
        ("book_flight", "Book a flight ticket"),
    ]
    tools = []
    for i in range(min(n, len(tool_defs))):
        name, desc = tool_defs[i]

        @tool(description=desc, name=name)
        def _fn(x: str = "") -> str:
            return "ok"

        tools.append(_fn)
    return tools


def _make_agent(mock_llm: MockLLM, tools: list[BaseTool] | None = None) -> Agent:
    return Agent(
        name="Test",
        role="assistant",
        llm=mock_llm,
        tools=tools or [],
    )


# ---------------------------------------------------------------------------
# 1. Tools ≤ threshold → skip filtering
# ---------------------------------------------------------------------------

def test_skip_filtering_when_tools_below_threshold(mock_llm):
    tools = _make_tools(5)
    selector = EmbeddingToolSelector(
        embed_fn=_keyword_embed_fn, top_k=3, min_tools_to_filter=10,
    )
    result = selector.select_tools(tools, "weather forecast")
    assert not result.was_filtered
    assert len(result.selected_tools) == len(tools)


# ---------------------------------------------------------------------------
# 2. Basic filtering: query matches relevant tools
# ---------------------------------------------------------------------------

def test_basic_filtering_selects_relevant_tools():
    tools = _make_tools(15)
    selector = EmbeddingToolSelector(
        embed_fn=_keyword_embed_fn, top_k=3, min_tools_to_filter=5,
    )
    result = selector.select_tools(tools, "weather forecast temperature")
    selected_names = {t.name for t in result.selected_tools}
    assert "get_weather" in selected_names
    assert result.was_filtered
    assert len(result.selected_tools) <= 3


# ---------------------------------------------------------------------------
# 3. used_tool_names always preserved
# ---------------------------------------------------------------------------

def test_used_tool_names_always_preserved():
    tools = _make_tools(15)
    selector = EmbeddingToolSelector(
        embed_fn=_keyword_embed_fn, top_k=3, min_tools_to_filter=5,
    )
    # "play_music" unlikely to match "weather" query, but should be preserved
    result = selector.select_tools(
        tools, "weather forecast", used_tool_names={"play_music"},
    )
    selected_names = {t.name for t in result.selected_tools}
    assert "play_music" in selected_names


# ---------------------------------------------------------------------------
# 4. top_k parameter controls selection count
# ---------------------------------------------------------------------------

def test_top_k_controls_selection_count():
    tools = _make_tools(15)
    selector = EmbeddingToolSelector(
        embed_fn=_keyword_embed_fn, top_k=2, min_tools_to_filter=5,
    )
    result = selector.select_tools(tools, "weather forecast temperature")
    assert len(result.selected_tools) <= 2


# ---------------------------------------------------------------------------
# 5. similarity_threshold filters low-score tools
# ---------------------------------------------------------------------------

def test_similarity_threshold_filters_low_score_tools():
    tools = _make_tools(15)
    selector = EmbeddingToolSelector(
        embed_fn=_keyword_embed_fn,
        top_k=10,
        similarity_threshold=0.99,
        min_tools_to_filter=5,
    )
    result = selector.select_tools(tools, "weather forecast temperature")
    # High threshold means fewer tools pass
    assert len(result.selected_tools) < len(tools)


# ---------------------------------------------------------------------------
# 6. Embedding cache reuse
# ---------------------------------------------------------------------------

def test_embedding_cache_reuse():
    call_count = 0

    def counting_embed_fn(texts: list[str]) -> list[list[float]]:
        nonlocal call_count
        call_count += 1
        return _keyword_embed_fn(texts)

    tools = _make_tools(15)
    selector = EmbeddingToolSelector(
        embed_fn=counting_embed_fn, top_k=3, min_tools_to_filter=5,
    )
    selector.select_tools(tools, "weather")
    initial_count = call_count
    selector.select_tools(tools, "calendar schedule")
    # Tool embeddings cached; only query embedding recalculated
    assert call_count == initial_count + 1  # +1 for query embed only


# ---------------------------------------------------------------------------
# 7. Cache invalidation
# ---------------------------------------------------------------------------

def test_cache_invalidation():
    call_count = 0

    def counting_embed_fn(texts: list[str]) -> list[list[float]]:
        nonlocal call_count
        call_count += 1
        return _keyword_embed_fn(texts)

    tools = _make_tools(15)
    selector = EmbeddingToolSelector(
        embed_fn=counting_embed_fn, top_k=3, min_tools_to_filter=5,
    )
    selector.select_tools(tools, "weather")
    selector.invalidate_cache()
    selector.select_tools(tools, "weather")
    # After invalidation, tool embeddings recomputed: 2 calls for tools + 2 for query
    assert call_count >= 3


# ---------------------------------------------------------------------------
# 8. Runner integration: selector reduces tools sent to LLM
# ---------------------------------------------------------------------------

def test_runner_with_selector_reduces_tools(mock_llm):
    tools = _make_tools(15)
    mock_llm.set_response("Done.")
    agent = _make_agent(mock_llm, tools=tools)
    selector = EmbeddingToolSelector(
        embed_fn=_keyword_embed_fn, top_k=3, min_tools_to_filter=5,
    )
    runner = Runner(agent, tool_selector=selector)
    result = runner.run("weather forecast")

    assert result.content == "Done."
    # LLM should receive fewer tools than total
    tools_sent = mock_llm.chat_calls[0]["tools"]
    assert len(tools_sent) < len(tools)
    assert len(tools_sent) <= 3


# ---------------------------------------------------------------------------
# 9. Runner integration: no selector = backward compatible
# ---------------------------------------------------------------------------

def test_runner_without_selector_backward_compatible(mock_llm):
    tools = _make_tools(15)
    mock_llm.set_response("Done.")
    agent = _make_agent(mock_llm, tools=tools)
    runner = Runner(agent)  # no selector
    result = runner.run("anything")

    assert result.content == "Done."
    tools_sent = mock_llm.chat_calls[0]["tools"]
    assert len(tools_sent) == len(tools)


# ---------------------------------------------------------------------------
# 10. tool_selection event fires correctly
# ---------------------------------------------------------------------------

def test_tool_selection_event_fires(mock_llm):
    tools = _make_tools(15)
    mock_llm.set_response("Done.")
    agent = _make_agent(mock_llm, tools=tools)
    selector = EmbeddingToolSelector(
        embed_fn=_keyword_embed_fn, top_k=3, min_tools_to_filter=5,
    )
    bus = EventBus()
    events = []
    bus.on("tool_selection", lambda d: events.append(d))

    runner = Runner(agent, event_bus=bus, tool_selector=selector)
    runner.run("weather")

    assert len(events) == 1
    assert events[0]["total_tools"] == 15
    assert events[0]["selected_tools"] <= 3
    assert events[0]["was_filtered"] is True
    assert "selected_names" in events[0]
    assert "scores" in events[0]


# ---------------------------------------------------------------------------
# 11. Cross-iteration used_tool_names tracking
# ---------------------------------------------------------------------------

def test_cross_iteration_used_tool_names_tracking(mock_llm):
    tools = _make_tools(15)

    # First iteration: LLM calls get_weather, second iteration: final text
    mock_llm.queue_responses([
        LLMResponse(
            tool_calls=[{"id": "tc1", "name": "get_weather", "arguments": {"x": "Tokyo"}}],
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        ),
        LLMResponse(content="Final answer.", usage={"prompt_tokens": 8, "completion_tokens": 3}),
    ])

    agent = _make_agent(mock_llm, tools=tools)
    selector = EmbeddingToolSelector(
        embed_fn=_keyword_embed_fn, top_k=3, min_tools_to_filter=5,
    )
    bus = EventBus()
    events = []
    bus.on("tool_selection", lambda d: events.append(d))

    runner = Runner(agent, event_bus=bus, tool_selector=selector)
    result = runner.run("send email about the meeting schedule")

    assert result.content == "Final answer."
    # Second iteration's selection should include get_weather (used in first iteration)
    assert len(events) == 2
    assert "get_weather" in events[1]["selected_names"]


# ---------------------------------------------------------------------------
# 12. _tool_to_text produces meaningful text
# ---------------------------------------------------------------------------

def test_tool_to_text():
    @tool(description="Search for products by keyword")
    def search_products(query: str, limit: int = 10) -> str:
        return ""

    text = _tool_to_text(search_products)
    assert "search_products" in text
    assert "Search for products" in text
    assert "query" in text


# ---------------------------------------------------------------------------
# 13. ToolSelectionResult.was_filtered property
# ---------------------------------------------------------------------------

def test_tool_selection_result_was_filtered():
    tools = _make_tools(5)
    result_filtered = ToolSelectionResult(
        selected_tools=tools[:3], all_tools=tools, scores={},
    )
    assert result_filtered.was_filtered is True

    result_all = ToolSelectionResult(
        selected_tools=tools, all_tools=tools, scores={},
    )
    assert result_all.was_filtered is False


# ---------------------------------------------------------------------------
# 14. All tools below threshold → only used tools returned
# ---------------------------------------------------------------------------

def test_all_tools_below_threshold_returns_used_only():
    tools = _make_tools(15)
    selector = EmbeddingToolSelector(
        embed_fn=_keyword_embed_fn,
        top_k=5,
        similarity_threshold=999.0,  # impossibly high
        min_tools_to_filter=5,
    )
    result = selector.select_tools(
        tools, "xyzzy gibberish", used_tool_names={"get_weather"},
    )
    selected_names = {t.name for t in result.selected_tools}
    assert selected_names == {"get_weather"}
