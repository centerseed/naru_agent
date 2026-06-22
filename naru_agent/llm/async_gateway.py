"""通用 async LLM gateway —— 單一 event loop 下的並發安全 LLM 出口。

動機：以 `uvicorn --workers 1`（單一 event loop）+ 高 containerConcurrency 部署的服務，
任何同步 LLM 呼叫都會凍住整條 event loop（一個用戶的慢呼叫拖垮全部）。本 gateway 提供
所有 LLM 呼叫的唯一非阻塞出口，任何用 naru_agent 的專案都可重用：

- `litellm.acompletion`：真 async I/O，等網路時讓出 event loop。
- per-call `asyncio.Semaphore(N)`：限全域在途 LLM 並發；滿載 fail-fast `LLMBusyError`。
- `asyncio.wait_for(..., timeout_s)`：逾時真的取消底層協程（關連線），不再吊死、不再背景燒額度。
- per-call acquire/release，`try/finally` 釋放（CancelledError/TimeoutError 也歸還，無洩漏）。

N 由 env `NARU_LLM_MAX_CONCURRENCY`（預設 8）設定，可由呼叫端覆寫。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import litellm

logger = logging.getLogger(__name__)


class LLMBusyError(Exception):
    """全域 LLM 並發已滿，請稍候（呼叫端可轉 HTTP 429）。"""


class AsyncLLMGateway:
    """並發安全的 async LLM 出口：per-call semaphore + asyncio.wait_for 真取消。"""

    def __init__(self, max_concurrency: int | None = None, admit_timeout_s: float = 0.5):
        n = max_concurrency or int(os.getenv("NARU_LLM_MAX_CONCURRENCY", "8"))
        self._sem = asyncio.Semaphore(n)
        self._admit_timeout_s = admit_timeout_s

    async def _call(self, params: dict, timeout_s: float) -> Any:
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=self._admit_timeout_s)
        except asyncio.TimeoutError:
            raise LLMBusyError("llm concurrency saturated")
        try:
            return await asyncio.wait_for(litellm.acompletion(**params), timeout=timeout_s)
        finally:
            self._sem.release()

    @staticmethod
    def _build_params(messages, *, model, tools, temperature, response_format, api_key) -> dict:
        params: dict[str, Any] = {"model": model, "messages": messages}
        if temperature is not None:
            params["temperature"] = temperature
        if tools:
            params["tools"] = tools
        if response_format is not None:
            params["response_format"] = response_format
        key = api_key or os.getenv("GEMINI_API_KEY")
        if key and model.startswith("gemini/"):
            params["api_key"] = key
        return params

    @staticmethod
    def _log_usage(model: str, usage_type: str, user_id: str, resp: Any) -> None:
        u = getattr(resp, "usage", None)
        logger.info(
            "naru_llm_usage model=%s usage_type=%s uid=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
            model, usage_type, user_id,
            getattr(u, "prompt_tokens", None), getattr(u, "completion_tokens", None),
            getattr(u, "total_tokens", None),
        )

    async def acomplete(self, messages, *, model, usage_type, user_id, timeout_s,
                        tools=None, temperature=None, response_format=None, api_key=None):
        params = self._build_params(messages, model=model, tools=tools, temperature=temperature,
                                    response_format=response_format, api_key=api_key)
        resp = await self._call(params, timeout_s)
        if not resp.choices:
            raise ValueError(f"LLM empty choices (safety filter / load). model={model}")
        self._log_usage(model, usage_type, user_id, resp)
        return resp

    async def acomplete_structured(self, messages, *, model, usage_type, user_id, timeout_s, api_key=None):
        """結構化輸出：response_format={"type":"json_object"} + json.loads（寬鬆解析，
        不用 Pydantic strict —— 對齊現行寬鬆解析行為，避免回退）。"""
        resp = await self.acomplete(messages, model=model, usage_type=usage_type, user_id=user_id,
                                    timeout_s=timeout_s, response_format={"type": "json_object"}, api_key=api_key)
        content = resp.choices[0].message.content
        return json.loads(content)


# module-level singleton（--workers 1 下 per-process=per-instance 全域有效）
llm_gateway = AsyncLLMGateway()
