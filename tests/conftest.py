"""全域 Mock fixtures：MockLLM, MockMemoryStore, MockMem0Client"""
from __future__ import annotations

import uuid
from collections import deque
from typing import Any
from unittest.mock import MagicMock

import pytest

from naru_agent.llm.base import BaseLLM, LLMResponse
from naru_agent.memory.base import MemoryItem, MemoryStore


# ---------------------------------------------------------------------------
# MockLLM
# ---------------------------------------------------------------------------

class MockLLM(BaseLLM):
    """可編程的假 LLM，供單元測試使用。"""

    def __init__(self):
        self._queue: deque[LLMResponse] = deque()
        self._default_response = LLMResponse(content="default response")
        self._structured_response: Any = None
        self.chat_calls: list[dict] = []
        self.structured_calls: list[dict] = []

    # --- 設定方法 ---

    def set_response(self, content: str) -> None:
        """設定下次 chat() 回純文字。"""
        self._default_response = LLMResponse(content=content)
        self._queue.clear()

    def set_tool_call_response(self, name: str, args: dict, final_text: str = "Done") -> None:
        """設定兩步序列：第一次回 tool call，第二次回純文字。"""
        self._queue.clear()
        self._queue.append(
            LLMResponse(
                tool_calls=[{"id": "mock_tc_1", "name": name, "arguments": args}],
                usage={"prompt_tokens": 10, "completion_tokens": 5},
            )
        )
        self._queue.append(LLMResponse(content=final_text, usage={"prompt_tokens": 8, "completion_tokens": 3}))

    def queue_responses(self, responses: list[LLMResponse]) -> None:
        """排入多個依序回應。"""
        for r in responses:
            self._queue.append(r)

    def set_structured_response(self, obj: Any) -> None:
        """設定 chat_structured() 的回傳值。"""
        self._structured_response = obj

    # --- BaseLLM 實作 ---

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> LLMResponse:
        self.chat_calls.append({"messages": messages, "tools": tools})
        if self._queue:
            return self._queue.popleft()
        return self._default_response

    def chat_structured(
        self,
        messages: list[dict],
        response_schema: type,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> Any:
        self.structured_calls.append({"messages": messages, "schema": response_schema})
        return self._structured_response


# ---------------------------------------------------------------------------
# MockMemoryStore
# ---------------------------------------------------------------------------

class MockMemoryStore(MemoryStore):
    """In-memory 假儲存，用於測試 MemoryManager。"""

    def __init__(self):
        self._items: dict[str, MemoryItem] = {}
        self.add_calls: list[dict] = []
        self.update_calls: list[dict] = []
        self.delete_calls: list[str] = []
        self.search_calls: list[dict] = []

    def seed(self, item: MemoryItem) -> None:
        """直接植入一筆記憶，不計入 add_calls。"""
        self._items[item.id] = item

    def add(self, item: MemoryItem, embedding: list[float]) -> None:
        self.add_calls.append({"item": item, "embedding": embedding})
        self._items[item.id] = item

    def search(self, user_id: str, embedding: list[float], top_k: int = 5) -> list[MemoryItem]:
        self.search_calls.append({"user_id": user_id, "embedding": embedding, "top_k": top_k})
        results = [i for i in self._items.values() if i.user_id == user_id]
        return results[:top_k]

    def update(self, item_id: str, content: str, embedding: list[float]) -> None:
        self.update_calls.append({"item_id": item_id, "content": content})
        if item_id in self._items:
            item = self._items[item_id]
            self._items[item_id] = item.model_copy(update={"content": content})

    def delete(self, item_id: str) -> None:
        self.delete_calls.append(item_id)
        self._items.pop(item_id, None)

    def get_all(self, user_id: str) -> list[MemoryItem]:
        return [i for i in self._items.values() if i.user_id == user_id]


# ---------------------------------------------------------------------------
# MockMem0Client
# ---------------------------------------------------------------------------

class MockMem0Client:
    """假 mem0 client，支援 OSS 與 Platform 兩種回傳格式。"""

    def __init__(self, format: str = "oss"):
        assert format in ("oss", "platform")
        self._format = format
        self._memories: list[dict] = []
        self.add_calls: list[dict] = []
        self.search_calls: list[dict] = []
        self.get_all_calls: list[dict] = []

    def _wrap(self, items: list[dict]) -> Any:
        if self._format == "oss":
            return {"results": items}
        return items

    def add(self, messages: list[dict], user_id: str, **kwargs) -> Any:
        self.add_calls.append({"messages": messages, "user_id": user_id})
        new_item = {
            "id": str(uuid.uuid4()),
            "memory": f"memory from {user_id}",
            "user_id": user_id,
            "event": "ADD",
        }
        self._memories.append(new_item)
        return self._wrap([{"event": "ADD", "memory": new_item["memory"]}])

    def search(self, query: str, user_id: str, limit: int = 5, **kwargs) -> Any:
        self.search_calls.append({"query": query, "user_id": user_id, "limit": limit})
        results = [m for m in self._memories if m.get("user_id") == user_id][:limit]
        return self._wrap(results)

    def get_all(self, user_id: str, **kwargs) -> Any:
        self.get_all_calls.append({"user_id": user_id})
        results = [m for m in self._memories if m.get("user_id") == user_id]
        return self._wrap(results)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm() -> MockLLM:
    return MockLLM()


@pytest.fixture
def mock_store() -> MockMemoryStore:
    return MockMemoryStore()


@pytest.fixture
def mock_mem0_client_oss() -> MockMem0Client:
    return MockMem0Client(format="oss")


@pytest.fixture
def mock_mem0_client_platform() -> MockMem0Client:
    return MockMem0Client(format="platform")


@pytest.fixture
def dummy_embed_fn():
    """回傳固定長度向量的假 embed function。"""
    return lambda text: [0.1] * 384
