"""Tools 單元測試"""
from __future__ import annotations

import pytest

from naru_agent.tools.base import FunctionTool, tool


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
