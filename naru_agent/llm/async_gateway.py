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


# 暫時性錯誤重試：Gemini / 上游偶發 503/502/504/429/連線重置是常態 burst，單發失敗會讓上層
# 判斷器（accept-intent / agreement / scope）直接降級成「沒同意」→ 使用者按了「要」卻被當沒反應、
# 落到「我還沒準備好變更」死路（2026-06-22 prod 實證：一個 503 把同意流程打斷）。舊的同步
# plan-edit 路徑本來就有 transient 退避重試；async gateway 改寫時漏掉，這裡補回。
# 純框架層、不引 app code：用 litellm 自家例外型別 + httpx status 判斷，字串比對僅作最後保底。
_TRANSIENT_STATUS = (429, 500, 502, 503, 504)
_MAX_TRANSIENT_RETRIES = 2
# 退避 = _TRANSIENT_BACKOFF_S * attempt → 第1次 2s、第2次 4s。「model is currently overloaded」
# 的 503 是 Google 端容量過載,0.4s 後通常還在過載、重試照樣失敗;拉到 2~4s 給上游恢復時間,
# 重試才真的救得回(2026-06-22 真 prod key 壓測:短退避救回率低)。退避期間不佔 semaphore 名額。
_TRANSIENT_BACKOFF_S = 2.0


def _is_transient_llm_error(exc: BaseException) -> bool:
    """上游暫時性錯誤（可短退避後重試），非永久性（400/401/schema）。"""
    transient_types = tuple(
        t for t in (
            getattr(litellm, "InternalServerError", None),
            getattr(litellm, "ServiceUnavailableError", None),
            getattr(litellm, "RateLimitError", None),
            getattr(litellm, "Timeout", None),
            getattr(litellm, "APIConnectionError", None),
            getattr(litellm, "APIError", None),
        )
        if isinstance(t, type)
    )
    if transient_types and isinstance(exc, transient_types):
        return True
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in _TRANSIENT_STATUS:
        return True
    status = getattr(exc, "status_code", None)
    if status in _TRANSIENT_STATUS:
        return True
    s = str(exc)
    return any(
        marker in s
        for marker in ("503", "502", "504", "429", "Service Unavailable",
                       "Internal", "overloaded", "RESOURCE_EXHAUSTED", "Connection reset")
    )


class AsyncLLMGateway:
    """並發安全的 async LLM 出口：per-call semaphore + asyncio.wait_for 真取消。"""

    def __init__(self, max_concurrency: int | None = None, admit_timeout_s: float = 0.5):
        n = max_concurrency or int(os.getenv("NARU_LLM_MAX_CONCURRENCY", "8"))
        self._sem = asyncio.Semaphore(n)
        self._admit_timeout_s = admit_timeout_s

    async def _call(self, params: dict, timeout_s: float) -> Any:
        # 每次嘗試「進名額 → 打 → 出名額」；transient 重試的 backoff 在『釋放名額之後』才睡,
        # 重試者不再佔著 semaphore 乾等 → 503 storm 不會被退避放大成 LLMBusyError storm
        # (2026-06-22 真 prod key 壓測實證:佔名額退避會把零星 503 放大成 busy 失敗)。
        attempt = 0
        while True:
            try:
                await asyncio.wait_for(self._sem.acquire(), timeout=self._admit_timeout_s)
            except asyncio.TimeoutError:
                raise LLMBusyError("llm concurrency saturated")
            backoff = None
            try:
                return await asyncio.wait_for(litellm.acompletion(**params), timeout=timeout_s)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                # 硬 deadline / 取消：不重試（重試會超出呼叫端時間預算），直接上拋。
                raise
            except Exception as exc:  # noqa: BLE001 — 由 _is_transient_llm_error 分流
                if not (_is_transient_llm_error(exc) and attempt < _MAX_TRANSIENT_RETRIES):
                    raise
                attempt += 1
                backoff = _TRANSIENT_BACKOFF_S * attempt
                logger.warning(
                    "llm transient error (retry %s/%s after %.1fs): %s",
                    attempt, _MAX_TRANSIENT_RETRIES, backoff, exc)
            finally:
                self._sem.release()
            # 只有 transient 重試路徑會走到這（成功 return / 其他例外 raise 都已離開）。
            await asyncio.sleep(backoff)  # backoff 不佔名額,睡完下一圈重新搶

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
