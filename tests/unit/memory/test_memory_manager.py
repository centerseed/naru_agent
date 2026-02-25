"""MemoryManager 單元測試"""
from __future__ import annotations

import uuid

import pytest

from naru_agent.memory.base import MemoryItem
from naru_agent.memory.manager import (
    ExtractedFacts,
    MemoryManager,
    ReconciliationAction,
    ReconciliationResult,
)
from tests.conftest import MockLLM, MockMemoryStore


@pytest.fixture
def manager(mock_llm, mock_store, dummy_embed_fn):
    return MemoryManager(llm=mock_llm, store=mock_store, embed_fn=dummy_embed_fn)


def _make_messages(text: str) -> list[dict]:
    return [
        {"role": "user", "content": text},
        {"role": "assistant", "content": "好的，我記住了。"},
    ]


# ---------------------------------------------------------------------------
# Duplicate hash skipped
# ---------------------------------------------------------------------------

def test_duplicate_hash_skipped(manager, mock_llm):
    mock_llm.set_structured_response(ExtractedFacts(facts=["喜歡台式料理"]))
    mock_llm.queue_responses([])  # chat() 不會被呼叫（structured only）
    # chat_structured 的回傳需設定，且 _reconcile 用到 chat_structured
    mock_llm.set_structured_response(ExtractedFacts(facts=["喜歡台式料理"]))

    messages = _make_messages("我喜歡台式料理")
    # 第一次 add
    manager.add("u1", messages)
    first_add_count = len(manager._seen_hashes)

    # 第二次 add 相同訊息
    result = manager.add("u1", messages)
    assert result == []
    assert len(manager._seen_hashes) == first_add_count  # hash set 不增加


# ---------------------------------------------------------------------------
# No facts returns empty
# ---------------------------------------------------------------------------

def test_no_facts_returns_empty(manager, mock_llm):
    mock_llm.set_structured_response(ExtractedFacts(facts=[]))
    result = manager.add("u1", _make_messages("test"))
    assert result == []


# ---------------------------------------------------------------------------
# ADD action calls store.add
# ---------------------------------------------------------------------------

def test_add_action_calls_store_add(mock_llm, mock_store, dummy_embed_fn):
    manager = MemoryManager(llm=mock_llm, store=mock_store, embed_fn=dummy_embed_fn)

    # structured_calls：第一次回 facts，第二次回 reconcile result
    call_count = [0]
    original_chat_structured = mock_llm.chat_structured

    def structured_side_effect(messages, response_schema, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return ExtractedFacts(facts=["喜歡台式料理"])
        return ReconciliationResult(actions=[
            ReconciliationAction(fact="喜歡台式料理", action="ADD")
        ])

    mock_llm.chat_structured = structured_side_effect

    manager.add("u1", _make_messages("test"))
    assert len(mock_store.add_calls) == 1
    assert mock_store.add_calls[0]["item"].content == "喜歡台式料理"


# ---------------------------------------------------------------------------
# UPDATE action calls store.update
# ---------------------------------------------------------------------------

def test_update_action_calls_store_update(mock_llm, mock_store, dummy_embed_fn):
    manager = MemoryManager(llm=mock_llm, store=mock_store, embed_fn=dummy_embed_fn)

    # 先植入一筆記憶
    existing_id = str(uuid.uuid4())
    mock_store.seed(MemoryItem(id=existing_id, user_id="u1", content="舊的記憶"))

    call_count = [0]

    def structured_side_effect(messages, response_schema, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return ExtractedFacts(facts=["新的記憶"])
        return ReconciliationResult(actions=[
            ReconciliationAction(fact="新的記憶", action="UPDATE", target_id="0", updated_text="新的記憶")
        ])

    mock_llm.chat_structured = structured_side_effect

    manager.add("u1", _make_messages("test"))
    assert len(mock_store.update_calls) == 1
    assert mock_store.update_calls[0]["content"] == "新的記憶"


# ---------------------------------------------------------------------------
# DELETE action calls store.delete
# ---------------------------------------------------------------------------

def test_delete_action_calls_store_delete(mock_llm, mock_store, dummy_embed_fn):
    manager = MemoryManager(llm=mock_llm, store=mock_store, embed_fn=dummy_embed_fn)

    existing_id = str(uuid.uuid4())
    mock_store.seed(MemoryItem(id=existing_id, user_id="u1", content="過期記憶"))

    call_count = [0]

    def structured_side_effect(messages, response_schema, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return ExtractedFacts(facts=["something"])
        return ReconciliationResult(actions=[
            ReconciliationAction(fact="過期記憶", action="DELETE", target_id="0")
        ])

    mock_llm.chat_structured = structured_side_effect

    manager.add("u1", _make_messages("test"))
    assert len(mock_store.delete_calls) == 1
    assert mock_store.delete_calls[0] == existing_id


# ---------------------------------------------------------------------------
# NONE action: no store call
# ---------------------------------------------------------------------------

def test_none_action_no_store_call(mock_llm, mock_store, dummy_embed_fn):
    manager = MemoryManager(llm=mock_llm, store=mock_store, embed_fn=dummy_embed_fn)

    existing_id = str(uuid.uuid4())
    mock_store.seed(MemoryItem(id=existing_id, user_id="u1", content="已有的記憶"))

    call_count = [0]

    def structured_side_effect(messages, response_schema, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return ExtractedFacts(facts=["已有的記憶"])
        return ReconciliationResult(actions=[
            ReconciliationAction(fact="已有的記憶", action="NONE")
        ])

    mock_llm.chat_structured = structured_side_effect

    manager.add("u1", _make_messages("test"))
    assert len(mock_store.add_calls) == 0
    assert len(mock_store.update_calls) == 0
    assert len(mock_store.delete_calls) == 0


# ---------------------------------------------------------------------------
# Empty existing → skip reconciliation, add all directly
# ---------------------------------------------------------------------------

def test_empty_existing_adds_all_facts_directly(mock_llm, mock_store, dummy_embed_fn):
    """當 store 中沒有現有記憶時，應跳過 reconciliation，直接 ADD 所有 facts。"""
    manager = MemoryManager(llm=mock_llm, store=mock_store, embed_fn=dummy_embed_fn)

    # 只設定 facts 回傳（reconcile 不應被呼叫）
    mock_llm.set_structured_response(ExtractedFacts(facts=["fact1", "fact2"]))

    manager.add("u1", _make_messages("test"))
    # reconcile 用 chat_structured 第二次呼叫，但 existing 為空時直接 ADD
    assert len(mock_store.add_calls) == 2


# ---------------------------------------------------------------------------
# search calls embed_fn and store
# ---------------------------------------------------------------------------

def test_search_calls_embed_fn_and_store(mock_llm, mock_store, dummy_embed_fn):
    manager = MemoryManager(llm=mock_llm, store=mock_store, embed_fn=dummy_embed_fn)
    mock_store.seed(MemoryItem(id="1", user_id="u1", content="台式料理"))

    results = manager.search("u1", "food preferences")
    assert len(mock_store.search_calls) == 1
    assert mock_store.search_calls[0]["user_id"] == "u1"
    assert isinstance(results, list)


# ---------------------------------------------------------------------------
# get_context_string format
# ---------------------------------------------------------------------------

def test_get_context_string_format(mock_llm, mock_store, dummy_embed_fn):
    manager = MemoryManager(llm=mock_llm, store=mock_store, embed_fn=dummy_embed_fn)
    mock_store.seed(MemoryItem(id="1", user_id="u1", content="fact1"))
    mock_store.seed(MemoryItem(id="2", user_id="u1", content="fact2"))

    ctx = manager.get_context_string("u1", "query")
    assert "- fact1" in ctx
    assert "- fact2" in ctx


def test_get_context_string_empty_when_no_memories(manager):
    ctx = manager.get_context_string("nobody", "query")
    assert ctx == ""


# ---------------------------------------------------------------------------
# _format_messages static method
# ---------------------------------------------------------------------------

def test_format_messages_static_method():
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
    ]
    result = MemoryManager._format_messages(messages)
    assert "user: Hello" in result
    assert "assistant: Hi there" in result
