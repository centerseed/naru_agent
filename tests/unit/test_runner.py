"""Runner 單元測試（核心，覆蓋所有分支）"""
from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from naru_agent.agent import Agent
from naru_agent.events import EventBus
from naru_agent.guardrails.keyword import KeywordGuardrail
from naru_agent.llm.base import LLMResponse
from naru_agent.runner import Runner
from naru_agent.tools.base import tool
from tests.conftest import MockLLM


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent(mock_llm, **kwargs) -> Agent:
    defaults = dict(name="Naru", role="assistant", llm=mock_llm)
    defaults.update(kwargs)
    return Agent(**defaults)


def make_tool_call_response(name: str, args: dict, tc_id: str = "tc_1") -> LLMResponse:
    return LLMResponse(
        tool_calls=[{"id": tc_id, "name": name, "arguments": args}],
        usage={"prompt_tokens": 10, "completion_tokens": 5},
    )


# ---------------------------------------------------------------------------
# 1. Happy path（無 tools / memory / guardrails）
# ---------------------------------------------------------------------------

def test_happy_path_no_tools_no_memory_no_guardrails(mock_llm):
    mock_llm.set_response("Hello!")
    agent = make_agent(mock_llm)
    runner = Runner(agent)
    result = runner.run("hi")

    assert result.content == "Hello!"
    assert result.blocked is False
    assert result.reason is None


# ---------------------------------------------------------------------------
# 2. Input guardrail blocks
# ---------------------------------------------------------------------------

def test_input_guardrail_blocks(mock_llm):
    guard = KeywordGuardrail(
        blocked_patterns=["forbidden"],
        input_message="Request blocked.",
    )
    agent = make_agent(mock_llm, guardrails=[guard])
    runner = Runner(agent)
    result = runner.run("please do forbidden thing")

    assert result.blocked is True
    assert result.content == "Request blocked."
    # LLM 不應被呼叫
    assert len(mock_llm.chat_calls) == 0


# ---------------------------------------------------------------------------
# 3. Output guardrail modifies content
# ---------------------------------------------------------------------------

def test_output_guardrail_modifies_content(mock_llm):
    mock_llm.set_response("This contains bad_word in the response.")
    guard = KeywordGuardrail(
        blocked_patterns=["bad_word"],
        output_replacement="Content filtered.",
    )
    agent = make_agent(mock_llm, guardrails=[guard])
    runner = Runner(agent)
    result = runner.run("test message")

    assert result.content == "Content filtered."
    assert result.blocked is False  # output guardrail 不設 blocked


# ---------------------------------------------------------------------------
# 4. Tool call flow
# ---------------------------------------------------------------------------

def test_tool_call_flow(mock_llm):
    @tool(description="Echo a message")
    def echo(msg: str) -> str:
        return f"echoed: {msg}"

    mock_llm.set_tool_call_response("echo", {"msg": "hello"}, final_text="Final answer.")
    agent = make_agent(mock_llm, tools=[echo])
    runner = Runner(agent)
    result = runner.run("test")

    assert result.content == "Final answer."
    # LLM 被呼叫兩次
    assert len(mock_llm.chat_calls) == 2
    # 第二次呼叫的 messages 含 tool result
    second_messages = mock_llm.chat_calls[1]["messages"]
    roles = [m["role"] for m in second_messages]
    assert "tool" in roles


# ---------------------------------------------------------------------------
# 5. Memory.get_context_string called with user_id
# ---------------------------------------------------------------------------

def test_memory_get_context_string_called_with_user_id(mock_llm):
    mock_llm.set_response("Response with memory.")
    memory = MagicMock()
    memory.get_context_string.return_value = "- 喜歡台式料理"
    memory.add.return_value = []

    agent = make_agent(mock_llm, memory=memory)
    runner = Runner(agent)
    runner.run("我想吃什麼好？", user_id="u1")

    memory.get_context_string.assert_called_once_with("u1", "我想吃什麼好？")


# ---------------------------------------------------------------------------
# 6. Memory.add called after response
# ---------------------------------------------------------------------------

def test_memory_add_called_after_response(mock_llm):
    mock_llm.set_response("OK.")
    memory = MagicMock()
    memory.get_context_string.return_value = ""
    memory.add.return_value = []

    agent = make_agent(mock_llm, memory=memory)
    runner = Runner(agent)
    runner.run("hello", user_id="u1")

    memory.add.assert_called_once()
    call_args = memory.add.call_args
    assert call_args[0][0] == "u1"
    messages_passed = call_args[0][1]
    roles = [m["role"] for m in messages_passed]
    assert "assistant" in roles
    assert "user" in roles


# ---------------------------------------------------------------------------
# 7. No memory call without user_id
# ---------------------------------------------------------------------------

def test_no_memory_call_without_user_id(mock_llm):
    mock_llm.set_response("OK.")
    memory = MagicMock()

    agent = make_agent(mock_llm, memory=memory)
    runner = Runner(agent)
    runner.run("hello")  # no user_id

    memory.get_context_string.assert_not_called()
    memory.add.assert_not_called()


# ---------------------------------------------------------------------------
# 8. Max iterations reached
# ---------------------------------------------------------------------------

def test_max_iterations_reached(mock_llm):
    @tool(description="Dummy tool")
    def dummy(x: str) -> str:
        return "ok"

    # 每次 LLM 都回 tool call
    mock_llm.queue_responses([
        make_tool_call_response("dummy", {"x": "1"}),
        make_tool_call_response("dummy", {"x": "2"}),
    ])

    agent = make_agent(mock_llm, tools=[dummy], max_iterations=2)
    runner = Runner(agent)
    result = runner.run("test")

    assert result.content == "Max iterations reached."


# ---------------------------------------------------------------------------
# 9. Conversation history included in messages
# ---------------------------------------------------------------------------

def test_conversation_history_included_in_messages(mock_llm):
    mock_llm.set_response("Got it.")
    history = [
        {"role": "user", "content": "previous question"},
        {"role": "assistant", "content": "previous answer"},
    ]
    agent = make_agent(mock_llm)
    runner = Runner(agent)
    runner.run("new question", conversation_history=history)

    messages = mock_llm.chat_calls[0]["messages"]
    contents = [m["content"] for m in messages]
    assert "previous question" in contents
    assert "previous answer" in contents
    assert "new question" in contents
    # history 必須在 new question 之前
    prev_idx = next(i for i, m in enumerate(messages) if m["content"] == "previous question")
    new_idx = next(i for i, m in enumerate(messages) if m["content"] == "new question")
    assert prev_idx < new_idx


# ---------------------------------------------------------------------------
# 10. Events fired in correct order
# ---------------------------------------------------------------------------

def test_events_fired_in_correct_order(mock_llm):
    mock_llm.set_response("Response.")
    agent = make_agent(mock_llm)
    bus = EventBus()
    event_log = []
    bus.on("before_llm_call", lambda d: event_log.append("before_llm_call"))
    bus.on("after_llm_call", lambda d: event_log.append("after_llm_call"))

    runner = Runner(agent, event_bus=bus)
    runner.run("hello")

    assert event_log.count("before_llm_call") == 1
    assert event_log.count("after_llm_call") == 1
    assert event_log.index("before_llm_call") < event_log.index("after_llm_call")


# ---------------------------------------------------------------------------
# 11. Tool events fired
# ---------------------------------------------------------------------------

def test_tool_events_fired(mock_llm):
    @tool(description="Test tool")
    def mytool(val: str) -> str:
        return val

    mock_llm.set_tool_call_response("mytool", {"val": "data"}, final_text="Done.")
    agent = make_agent(mock_llm, tools=[mytool])
    bus = EventBus()
    before_calls = []
    after_calls = []
    bus.on("before_tool_call", lambda d: before_calls.append(d))
    bus.on("after_tool_call", lambda d: after_calls.append(d))

    runner = Runner(agent, event_bus=bus)
    runner.run("run tool")

    assert len(before_calls) == 1
    assert before_calls[0]["tool"] == "mytool"
    assert len(after_calls) == 1
    assert after_calls[0]["tool"] == "mytool"


# ---------------------------------------------------------------------------
# 12. Usage accumulated across iterations
# ---------------------------------------------------------------------------

def test_usage_accumulated_across_iterations(mock_llm):
    @tool(description="Dummy")
    def dummy(x: str) -> str:
        return "ok"

    mock_llm.queue_responses([
        LLMResponse(
            tool_calls=[{"id": "tc1", "name": "dummy", "arguments": {"x": "1"}}],
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        ),
        LLMResponse(
            content="Final.",
            usage={"prompt_tokens": 8, "completion_tokens": 3},
        ),
    ])

    agent = make_agent(mock_llm, tools=[dummy])
    runner = Runner(agent)
    result = runner.run("go")

    assert result.usage.get("prompt_tokens") == 18
    assert result.usage.get("completion_tokens") == 8
