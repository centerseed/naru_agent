"""Agent 單元測試"""
from __future__ import annotations

import pytest

from naru_agent.agent import Agent
from naru_agent.guardrails.keyword import KeywordGuardrail
from naru_agent.tools.base import tool
from tests.conftest import MockLLM, MockMemoryStore


@pytest.fixture
def simple_agent(mock_llm):
    return Agent(name="Naru", role="assistant", llm=mock_llm)


def test_minimal_agent_creation(mock_llm):
    agent = Agent(name="Naru", role="assistant", llm=mock_llm)
    assert agent.name == "Naru"
    assert agent.role == "assistant"
    assert agent.goal == ""
    assert agent.tools == []
    assert agent.memory is None
    assert agent.guardrails == []
    assert agent.max_iterations == 10


def test_agent_with_all_fields(mock_llm, mock_store, dummy_embed_fn):
    from naru_agent.memory.manager import MemoryManager

    @tool(description="A test tool")
    def my_tool(query: str) -> str:
        return query

    guard = KeywordGuardrail(blocked_patterns=["bad"])
    mem = MemoryManager(llm=mock_llm, store=mock_store, embed_fn=dummy_embed_fn)

    agent = Agent(
        name="Naru",
        role="assistant",
        goal="help users",
        llm=mock_llm,
        tools=[my_tool],
        memory=mem,
        guardrails=[guard],
        max_iterations=5,
    )

    assert len(agent.tools) == 1
    assert agent.memory is mem
    assert len(agent.guardrails) == 1
    assert agent.max_iterations == 5
    assert agent.goal == "help users"


def test_system_message_without_goal_or_memory(simple_agent):
    msg = simple_agent.get_system_message()
    assert "You are Naru, a assistant." in msg
    assert "goal" not in msg.lower()
    assert "## Relevant User Context" not in msg


def test_system_message_with_goal(mock_llm):
    agent = Agent(name="Naru", role="coach", goal="help users reach their fitness goals", llm=mock_llm)
    msg = agent.get_system_message()
    assert "You are Naru, a coach." in msg
    assert "help users reach their fitness goals" in msg


def test_system_message_with_custom_system_prompt(mock_llm):
    agent = Agent(
        name="Naru",
        role="coach",
        system_prompt="You are a custom assistant.",
        llm=mock_llm,
    )
    msg = agent.get_system_message()
    assert msg == "You are a custom assistant."
    assert "You are Naru" not in msg


def test_system_message_with_memory_context(simple_agent):
    msg = simple_agent.get_system_message(memory_context="- 喜歡台式料理\n- 討厭麻辣")
    assert "## Relevant User Context" in msg
    assert "喜歡台式料理" in msg


def test_empty_memory_context_not_injected(simple_agent):
    msg = simple_agent.get_system_message(memory_context="")
    assert "## Relevant User Context" not in msg


def test_get_tool_schemas_empty(simple_agent):
    assert simple_agent.get_tool_schemas() == []


def test_get_tool_schemas_returns_openai_format(mock_llm):
    @tool(description="Search for products")
    def search_products(query: str) -> str:
        return query

    agent = Agent(name="Naru", role="assistant", llm=mock_llm, tools=[search_products])
    schemas = agent.get_tool_schemas()

    assert len(schemas) == 1
    schema = schemas[0]
    assert schema["type"] == "function"
    func = schema["function"]
    assert "name" in func
    assert "description" in func
    assert func["parameters"]["type"] == "object"


def test_get_tool_by_name_found(mock_llm):
    @tool(description="A tool")
    def my_tool(x: str) -> str:
        return x

    agent = Agent(name="Naru", role="assistant", llm=mock_llm, tools=[my_tool])
    found = agent.get_tool_by_name("my_tool")
    assert found is my_tool


def test_get_tool_by_name_not_found(mock_llm):
    agent = Agent(name="Naru", role="assistant", llm=mock_llm)
    assert agent.get_tool_by_name("nonexistent") is None
