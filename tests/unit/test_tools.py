"""Tools 單元測試"""
from __future__ import annotations

import asyncio

import pytest

from naru_agent.tools.base import BaseTool, FunctionTool, tool


def test_tool_decorator_creates_function_tool():
    @tool(description="A simple tool")
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    assert isinstance(greet, FunctionTool)
    assert greet.name == "greet"
    assert greet.description == "A simple tool"


def test_tool_schema_has_required_fields():
    @tool(description="Search products")
    def search(query: str) -> str:
        return query

    schema = search.to_schema()
    assert schema["type"] == "function"
    func = schema["function"]
    assert func["name"] == "search"
    assert func["description"] == "Search products"
    assert func["parameters"]["type"] == "object"
    assert "query" in func["parameters"]["properties"]


def test_tool_run_calls_underlying_function():
    @tool(description="Add two numbers")
    def add(a: int, b: int) -> int:
        return a + b

    result = add.run(a=2, b=3)
    assert result == "5"


def test_tool_with_multiple_args():
    @tool(description="Combine strings")
    def combine(first: str, second: str, separator: str = "-") -> str:
        return f"{first}{separator}{second}"

    result = combine.run(first="hello", second="world")
    assert result == "hello-world"

    result2 = combine.run(first="a", second="b", separator="/")
    assert result2 == "a/b"


# ---------------------------------------------------------------------------
# Edge-case tests — Fix #1 & #2
# ---------------------------------------------------------------------------

class TestAsyncToolSupport:
    """Fix #1: async func in sync run() should work even inside existing event loop.
    Fix #2: arun() should use get_running_loop() not get_event_loop()."""

    @pytest.mark.asyncio
    async def test_async_function_tool_arun(self):
        """arun() should natively await async functions."""
        async def async_greet(name: str) -> str:
            await asyncio.sleep(0)  # simulate async work
            return f"Hello {name}!"

        tool = FunctionTool(async_greet, name="greet", description="Async greet")
        result = await tool.arun(name="World")
        assert result == "Hello World!"

    @pytest.mark.asyncio
    async def test_sync_function_tool_arun(self):
        """arun() should wrap sync functions via run_in_executor."""
        def sync_add(a: int, b: int) -> int:
            return a + b

        tool = FunctionTool(sync_add, name="add", description="Add")
        result = await tool.arun(a=2, b=3)
        assert result == "5"

    @pytest.mark.asyncio
    async def test_base_tool_arun_uses_get_running_loop(self):
        """BaseTool.arun() should use get_running_loop() (not get_event_loop)."""
        class SyncOnlyTool(BaseTool):
            name = "sync_tool"
            description = "A sync tool"
            args_schema = None

            def run(self, **kwargs):
                return "sync_result"

        tool = SyncOnlyTool()
        result = await tool.arun()
        assert result == "sync_result"

    def test_async_function_tool_sync_run_outside_loop(self):
        """Sync run() of async func should work when no event loop is running."""
        async def async_func() -> str:
            return "async_result"

        tool = FunctionTool(async_func, name="af", description="Async func")
        result = tool.run()
        assert result == "async_result"

    @pytest.mark.asyncio
    async def test_async_function_tool_sync_run_inside_loop(self):
        """Fix #1: sync run() of async func inside existing event loop should not crash."""
        async def async_func(x: int) -> int:
            return x * 2

        tool = FunctionTool(async_func, name="double", description="Double")
        # This would crash with asyncio.run() before the fix
        result = tool.run(x=5)
        assert result == "10"

    @pytest.mark.asyncio
    async def test_tool_returning_none(self):
        """Tool returning None should produce empty string."""
        async def noop() -> None:
            pass

        tool = FunctionTool(noop, name="noop", description="No-op")
        result = await tool.arun()
        assert result == ""
