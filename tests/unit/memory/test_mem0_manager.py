"""Mem0MemoryManager 單元測試（mock mem0 module，不需真實外部服務）"""
from __future__ import annotations

import sys
import uuid
from unittest.mock import MagicMock

import pytest

# 在 import Mem0MemoryManager 之前 mock mem0，避免 ImportError
if "mem0" not in sys.modules:
    sys.modules["mem0"] = MagicMock()

from naru_agent.memory.mem0_manager import Mem0MemoryManager  # noqa: E402
from tests.conftest import MockMem0Client  # noqa: E402


# ---------------------------------------------------------------------------
# _normalise_add_result
# ---------------------------------------------------------------------------

def test_normalise_oss_format():
    result = {"results": [{"event": "ADD", "memory": "test"}]}
    normalised = Mem0MemoryManager._normalise_add_result(result)
    assert normalised == [{"event": "ADD", "memory": "test"}]


def test_normalise_platform_format():
    result = [{"event": "ADD", "memory": "test"}]
    normalised = Mem0MemoryManager._normalise_add_result(result)
    assert normalised == [{"event": "ADD", "memory": "test"}]


def test_normalise_empty_dict():
    normalised = Mem0MemoryManager._normalise_add_result({"results": []})
    assert normalised == []


def test_normalise_empty_list():
    normalised = Mem0MemoryManager._normalise_add_result([])
    assert normalised == []


def test_normalise_unknown_type():
    normalised = Mem0MemoryManager._normalise_add_result("unknown")
    assert normalised == []


# ---------------------------------------------------------------------------
# _to_memory_items
# ---------------------------------------------------------------------------

def test_to_memory_items_oss_format():
    result = {"results": [{"id": "abc", "memory": "喜歡台式料理", "user_id": "u1"}]}
    items = Mem0MemoryManager._to_memory_items(result, "u1")
    assert len(items) == 1
    assert items[0].id == "abc"
    assert items[0].content == "喜歡台式料理"


def test_to_memory_items_platform_format():
    result = [{"id": "xyz", "memory": "討厭麻辣", "user_id": "u1"}]
    items = Mem0MemoryManager._to_memory_items(result, "u1")
    assert len(items) == 1
    assert items[0].content == "討厭麻辣"


def test_to_memory_items_missing_fields_use_defaults():
    result = [{"memory": "no id entry"}]
    items = Mem0MemoryManager._to_memory_items(result, "u1")
    assert len(items) == 1
    assert items[0].user_id == "u1"
    assert items[0].content == "no id entry"
    # id 應有 fallback（uuid4）
    assert items[0].id != ""


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------

def test_add_calls_client_with_user_id(mock_mem0_client_oss):
    manager = Mem0MemoryManager(client=mock_mem0_client_oss)
    messages = [{"role": "user", "content": "test"}]
    manager.add("u1", messages)

    assert len(mock_mem0_client_oss.add_calls) == 1
    assert mock_mem0_client_oss.add_calls[0]["user_id"] == "u1"
    assert mock_mem0_client_oss.add_calls[0]["messages"] == messages


# ---------------------------------------------------------------------------
# search — 驗證傳 limit 而非 top_k
# ---------------------------------------------------------------------------

def test_search_passes_limit_not_top_k(mock_mem0_client_oss):
    # 先 add 一筆讓 search 有東西
    mock_mem0_client_oss._memories.append({
        "id": "1",
        "memory": "test memory",
        "user_id": "u1",
    })
    manager = Mem0MemoryManager(client=mock_mem0_client_oss)
    manager.search("u1", "query", top_k=5)

    assert len(mock_mem0_client_oss.search_calls) == 1
    call = mock_mem0_client_oss.search_calls[0]
    assert "limit" in call
    assert call["limit"] == 5
    assert "top_k" not in call


# ---------------------------------------------------------------------------
# get_all
# ---------------------------------------------------------------------------

def test_get_all_calls_client_with_user_id(mock_mem0_client_oss):
    manager = Mem0MemoryManager(client=mock_mem0_client_oss)
    manager.get_all("u1")

    assert len(mock_mem0_client_oss.get_all_calls) == 1
    assert mock_mem0_client_oss.get_all_calls[0]["user_id"] == "u1"


# ---------------------------------------------------------------------------
# get_context_string
# ---------------------------------------------------------------------------

def test_get_context_string_formatted_correctly(mock_mem0_client_oss):
    mock_mem0_client_oss._memories.append({
        "id": "1",
        "memory": "喜歡台式料理",
        "user_id": "u1",
    })
    manager = Mem0MemoryManager(client=mock_mem0_client_oss)
    ctx = manager.get_context_string("u1", "飲食偏好")
    assert "- 喜歡台式料理" in ctx


def test_get_context_string_empty_when_no_memories(mock_mem0_client_oss):
    manager = Mem0MemoryManager(client=mock_mem0_client_oss)
    ctx = manager.get_context_string("nobody", "query")
    assert ctx == ""


# ---------------------------------------------------------------------------
# OSS & Platform client both work
# ---------------------------------------------------------------------------

def test_oss_and_platform_client_both_work():
    for fmt in ("oss", "platform"):
        client = MockMem0Client(format=fmt)
        manager = Mem0MemoryManager(client=client)
        messages = [{"role": "user", "content": "test"}]
        result = manager.add("u1", messages)
        assert isinstance(result, list)
        # add 後 get_all 應有記憶
        memories = manager.get_all("u1")
        assert len(memories) >= 1
        assert memories[0].user_id == "u1"
