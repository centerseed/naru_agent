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

# 跨供應商 fallback:primary(通常 gemini)同 model transient 重試耗盡後,改打別家 model
# 頂上(env 設定,逗號分隔;空=維持現狀、完全不跨家)。只在暫時性錯誤(503/429/連線重置…)
# 觸發 —— 永久錯(400/schema)與硬 deadline(timeout/cancel)不觸發(換家也救不了或超時間預算)。
# Gemini 全過載時(2026-06 prod 503 storm)Rizo 不再整條死在「系統忙線中」。
# 每次呼叫即時讀 env,方便用 env flag 安全開關(key 未備好就維持空值=不啟用)。
_FALLBACK_MODELS_ENV = "NARU_LLM_FALLBACK_MODELS"


def _get_fallback_models() -> list[str]:
    raw = os.getenv(_FALLBACK_MODELS_ENV, "")
    return [m.strip() for m in raw.split(",") if m.strip()]


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

    async def _call(self, params: dict, timeout_s: float, *, allow_retry: bool = True) -> Any:
        # 每次嘗試「進名額 → 打 → 出名額」；transient 重試的 backoff 在『釋放名額之後』才睡,
        # 重試者不再佔著 semaphore 乾等 → 503 storm 不會被退避放大成 LLMBusyError storm
        # (2026-06-22 真 prod key 壓測實證:佔名額退避會把零星 503 放大成 busy 失敗)。
        #
        # allow_retry=False(acomplete 對「非最後一顆 model」傳入):一失敗就上拋、不原地重試,
        # 讓 acomplete 立刻切下一家(fail-fast)。治 T-0130 案例3:gemini 過載 storm 時原地
        # 2-4s 重試會燒光 timeout 預算、還可能撞 timeout_s 逾時,而逾時原本直接上拋、Mistral
        # 從沒被觸發。只有鏈上「最後一顆」(無處可切)才做 same-model transient 重試當保險。
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
                # (逾時的「換家」由 acomplete 決策:非最後一顆 → 切 fallback;最後一顆 → 上拋。)
                raise
            except Exception as exc:  # noqa: BLE001 — 由 _is_transient_llm_error 分流
                if not (allow_retry and _is_transient_llm_error(exc) and attempt < _MAX_TRANSIENT_RETRIES):
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
        # primary model 一失敗(暫時性錯誤或逾時)就立刻切下一家(fail-fast,不原地重試燒時間);
        # 只有鏈上最後一顆(無處可切)才 same-model transient 重試當保險。fallback 觸發/成功都打 log,
        # 維運可 grep naru_llm_fallback_trigger / naru_llm_fallback_success 看是否頂上成功。
        # T-0130 案例3 修正:①gemini 過載 storm 一 503 就換 Mistral,不原地 retry 到逾時;
        # ②primary【逾時】也視同失敗換家(舊 code 逾時直接上拋 → Mistral 從沒被觸發、用戶撞 busy)。
        fallbacks = [m for m in _get_fallback_models() if m != model]
        models_to_try = [model, *fallbacks]
        last_exc: BaseException | None = None
        for idx, m in enumerate(models_to_try):
            is_last = idx == len(models_to_try) - 1
            remaining = models_to_try[idx + 1:]
            params = self._build_params(messages, model=m, tools=tools, temperature=temperature,
                                        response_format=response_format, api_key=api_key)
            try:
                # 非最後一顆 → allow_retry=False(fail-fast 換家);最後一顆 → 保留 same-model 重試。
                resp = await self._call(params, timeout_s, allow_retry=is_last)
            except asyncio.CancelledError:
                raise  # 外層硬 deadline 取消:換家也超出呼叫端總預算,直接上拋
            except LLMBusyError:
                raise  # 並發飽和:同一 gateway semaphore,換家照樣飽和
            except asyncio.TimeoutError as exc:
                # primary 逾時(model 太慢)= 該 model 失敗;有 fallback 就換家(A 修)。
                last_exc = exc
                if remaining:
                    logger.warning(
                        "naru_llm_fallback_trigger primary=%s failed_model=%s next=%s "
                        "reason=timeout usage_type=%s uid=%s",
                        model, m, remaining[0], usage_type, user_id)
                    continue
                raise  # 已無 fallback → 維持逾時上拋
            except Exception as exc:  # noqa: BLE001 — 由 _is_transient_llm_error 分流
                last_exc = exc
                if remaining and _is_transient_llm_error(exc):
                    logger.warning(
                        "naru_llm_fallback_trigger primary=%s failed_model=%s next=%s "
                        "reason=%s usage_type=%s uid=%s",
                        model, m, remaining[0], type(exc).__name__, usage_type, user_id)
                    continue
                raise  # 永久錯 / 已無 fallback → 維持原本上拋行為
            if not resp.choices:
                raise ValueError(f"LLM empty choices (safety filter / load). model={m}")
            if idx > 0:
                logger.warning(
                    "naru_llm_fallback_success primary=%s fallback_model=%s usage_type=%s uid=%s",
                    model, m, usage_type, user_id)
            self._log_usage(m, usage_type, user_id, resp)
            return resp
        raise last_exc  # type: ignore[misc]  # 迴圈非空時不會走到

    async def acomplete_structured(self, messages, *, model, usage_type, user_id, timeout_s, api_key=None):
        """結構化輸出：response_format={"type":"json_object"} + json.loads（寬鬆解析，
        不用 Pydantic strict —— 對齊現行寬鬆解析行為，避免回退）。"""
        resp = await self.acomplete(messages, model=model, usage_type=usage_type, user_id=user_id,
                                    timeout_s=timeout_s, response_format={"type": "json_object"}, api_key=api_key)
        content = resp.choices[0].message.content
        return json.loads(content)


# module-level singleton（--workers 1 下 per-process=per-instance 全域有效）
llm_gateway = AsyncLLMGateway()
