"""Tests for NaruToolkit adapter."""

from __future__ import annotations

from typing import Literal
from unittest.mock import MagicMock, patch

import pytest

from naru_agent.tools.base import BaseTool, FunctionTool, tool
from naru_agent.tools.agno_adapter import NaruToolkit, _build_wrapper


class TestBuildWrapper:
    def test_wraps_function_tool(self):
        @tool(description="Add two numbers")
        def add(a: int, b: int) -> str:
            return str(a + b)

        wrapper = _build_wrapper(add)
        assert wrapper.__name__ == "add"
        assert wrapper.__doc__ == "Add two numbers"
        result = wrapper(a=2, b=3)
        assert result == "5"

    def test_wraps_no_args_tool(self):
        class NoArgsTool(BaseTool):
            name = "ping"
            description = "Return pong"
            args_schema = None

            def run(self, **kwargs):
                return "pong"

        t = NoArgsTool()
        wrapper = _build_wrapper(t)
        assert wrapper() == "pong"

    def test_wrapper_has_annotations(self):
        @tool(description="Search by query")
        def search(query: str, limit: int = 5) -> str:
            return f"{query}:{limit}"

        wrapper = _build_wrapper(search)
        assert "query" in wrapper.__annotations__
        assert wrapper.__annotations__["return"] is str


class TestNaruToolkit:
    def test_registered_agno_function_preserves_parameter_schema(self):
        @tool(description="Search workouts by local date")
        def workouts_on_date(
            mode: Literal["recent", "on_date"], date: str, count: int = 5
        ) -> str:
            return f"{mode}:{date}:{count}"

        adapter = NaruToolkit([workouts_on_date])
        registered = adapter.toolkit.functions["workouts_on_date"]

        properties = registered.parameters["properties"]
        assert properties["mode"]["enum"] == ["recent", "on_date"]
        assert properties["date"]["type"] == "string"
        assert properties["count"]["type"] == "integer"
        assert properties["count"]["default"] == 5
        assert registered.parameters["required"] == ["mode", "date"]

    def test_registers_tools(self):
        @tool(description="Tool A")
        def tool_a(x: str) -> str:
            return x

        @tool(description="Tool B")
        def tool_b(y: int) -> str:
            return str(y)

        with patch("agno.tools.toolkit.Toolkit") as MockToolkit:
            mock_instance = MagicMock()
            MockToolkit.return_value = mock_instance

            adapter = NaruToolkit([tool_a, tool_b])
            assert mock_instance.register.call_count == 2
            assert adapter.toolkit is mock_instance

    def test_handles_registration_failure(self):
        @tool(description="Bad tool")
        def bad_tool(x: str) -> str:
            return x

        with patch("agno.tools.toolkit.Toolkit") as MockToolkit:
            mock_instance = MagicMock()
            mock_instance.register.side_effect = Exception("fail")
            MockToolkit.return_value = mock_instance

            # Should not raise
            adapter = NaruToolkit([bad_tool])
            assert adapter.toolkit is mock_instance
