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
import threading
import time
from typing import Any

import litellm

from naru_agent.llm.delta_sink import DeltaSink, current_delta_sink

logger = logging.getLogger(__name__)


class LLMBusyError(Exception):
    """全域 LLM 並發已滿，請稍候（呼叫端可轉 HTTP 429）。"""


class StreamReassemblyError(Exception):
    """串流塊重組回 ModelResponse 失敗 —— 我方(litellm 重組)的錯,不是上游暫時性錯誤。

    litellm.stream_chunk_builder 內部失敗時會包成 litellm.APIError(status_code=500),
    那會被 _is_transient_llm_error 判成 transient → 白燒一次 LLM 呼叫 + 一顆 fallback
    供應商去重跑一個「重組 bug」。這裡改拋自家型別(不帶上游狀態碼/關鍵字)讓它 fail-fast。
    """


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

# 只有主 coach 的回覆會逐字串給用戶。其餘 usage_type(compression / intent / judge /
# 課表生成 / 跑步分析…)即使 request 裝了 sink 也不進串流路徑,行為位元級不變。
STREAMABLE_USAGE_TYPES = frozenset({"rizo_coach"})


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


def _plan_attempts(model: str, per_call_fallbacks: list[str] | None = None) -> list[str]:
    """換家順序(單一來源):primary → 呼叫端 per-usage fallback → env 跨供應商 fallback。

    per_call_fallbacks 由呼叫端從 agent_models.yaml 的 per-usage `model_fallbacks`
    讀出後傳入 —— naru_agent 是獨立 lib,不得 import app 層的 core.llm.agent_model_config,
    所以設定只能用「注入」而非「自己去讀」。順序與 LiteLLMAdapter._model_ladder 對齊:
    per-usage 先於 provider/env 級 fallback。去重、去掉與 primary 相同者,保序。

    帶 tools 的請求不特別處理:實測(litellm 1.83.0,prod 同版)Mistral chat completions
    對標準 OpenAI function tools 完全支援,gemini 503 → mistral 是有效退路。T-0220 原本以
    「Mistral 不吃自訂 tools」為由剔除 mistral,經真實 toolset 對 mistral-small-latest 打
    測全數回 tool_calls 成功而推翻,已移除該剔除(否則等於白白廢掉 tools 場景的唯一退路)。
    """
    ladder = [model]
    for candidate in [*(per_call_fallbacks or []), *_get_fallback_models()]:
        if not candidate or candidate in ladder:
            continue
        ladder.append(candidate)
    return ladder


def _last_model_retry_schedule() -> list[float]:
    """鏈上最後一顆 model 的 same-model transient 重試 backoff 秒序(policy 資料)。
    設計為 async/sync 共用同一份 backoff 排程(紅隊 B1);目前尚未接線,待後續 _call_sync 接上。"""
    return [_TRANSIENT_BACKOFF_S * (i + 1) for i in range(_MAX_TRANSIENT_RETRIES)]


class AsyncLLMGateway:
    """並發安全的 async LLM 出口：per-call semaphore + asyncio.wait_for 真取消。"""

    def __init__(self, max_concurrency: int | None = None, admit_timeout_s: float = 0.5):
        n = max_concurrency or int(os.getenv("NARU_LLM_MAX_CONCURRENCY", "8"))
        self._sem = asyncio.Semaphore(n)
        self._admit_timeout_s = admit_timeout_s
        # sync 入口(complete_sync)專用並發閘:不借 asyncio default executor、
        # 不吃 async semaphore(asyncio.Semaphore 不能跨 thread)。滿載 fail-fast LLMBusyError,
        # 避免 fallback 拉長的 sync 呼叫在 503 storm 下餓死共用 ThreadPoolExecutor(紅隊 B2)。
        n_sync = int(os.getenv("NARU_LLM_SYNC_MAX_CONCURRENCY", str(n)))
        self._sync_sem = threading.Semaphore(n_sync)

    async def _acompletion(self, params: dict, sink: DeltaSink | None) -> Any:
        """唯一的 litellm 呼叫點。無 sink → 與改動前完全相同的一行。

        有 sink → 開 stream 逐塊推 delta,再用 litellm.stream_chunk_builder 重組回
        一個完整 ModelResponse 回傳。呼叫端(agno)拿到的東西與非串流時同構,因此
        agno 永遠不需要進 streaming mode、ainvoke_stream 永不被呼叫,gateway 的
        semaphore / 逾時 / fallback / 逐通 log 全部原封不動地繼續生效。
        """
        if sink is None:
            return await litellm.acompletion(**params)

        chunks: list[Any] = []
        stream = await litellm.acompletion(
            **params, stream=True, stream_options={"include_usage": True})
        try:
            async for chunk in stream:
                chunks.append(chunk)
                choices = getattr(chunk, "choices", None) or ()
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                text = getattr(delta, "content", None)
                if text:
                    sink.push(text)
        finally:
            # 逾時(wait_for 取消 async for)/ 供應商中途斷線都會直接離開迴圈,stream 被丟掉、
            # 底層 httpx response 撐到 GC 才關 —— 正好是 503/timeout storm(fallback 存在的理由)
            # 最不能漏連線的時候。CustomStreamWrapper 有 aclose(),明確關掉。
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception as exc:  # noqa: BLE001 — 收尾失敗不得蓋掉真正的錯
                    logger.warning("llm stream aclose failed: %s", exc)

        try:
            resp = litellm.stream_chunk_builder(chunks, messages=params.get("messages"))
        except Exception as exc:  # noqa: BLE001 — 重組失敗是我方 bug,不可偽裝成 transient
            logger.error("llm stream reassembly failed: %s", exc)
            raise StreamReassemblyError(
                f"streamed response reassembly failed: {type(exc).__name__}") from exc
        if resp is None:
            raise StreamReassemblyError("streamed response could not be reassembled")

        # agno 會丟棄「與 tool_calls 一起吐出來」的 prose(它只執行工具、再發一通拿正文)。
        # 我們已經把那段 prose 串給用戶了 → 叫 client 清掉,別留下最後不會出現的半句。
        #
        # ⚠️ 不能只看 finish_reason:我們送 stream_options={"include_usage": True},litellm 會在
        # 尾端多吐一塊 usage-only chunk,而那塊的 choices 不是空的(finish_reason=None),
        # stream_chunk_builder 對每個「choices 非空」的 chunk 覆寫 finish_reason → "tool_calls"
        # 被尾塊蓋成 "stop"(litellm 1.83.0 實證)。以重組後的 message.tool_calls 為主判準。
        choices = getattr(resp, "choices", None) or ()
        if choices and sink.pushed_since_reset:
            msg = getattr(choices[0], "message", None)
            if (getattr(msg, "tool_calls", None)
                    or getattr(choices[0], "finish_reason", None) == "tool_calls"):
                sink.reset()
        return resp

    async def _call(self, params: dict, timeout_s: float, *, allow_retry: bool = True,
                    sink: DeltaSink | None = None) -> Any:
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
                return await asyncio.wait_for(
                    self._acompletion(params, sink), timeout=timeout_s)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                # 硬 deadline / 取消：不重試（重試會超出呼叫端時間預算），直接上拋。
                # (逾時的「換家」由 acomplete 決策:非最後一顆 → 切 fallback;最後一顆 → 上拋。)
                raise
            except Exception as exc:  # noqa: BLE001 — 由 _is_transient_llm_error 分流
                if not (allow_retry and _is_transient_llm_error(exc) and attempt < _MAX_TRANSIENT_RETRIES):
                    raise
                attempt += 1
                # same-model 重試 = 重問一次,已串出去的半句不會出現在最終答案裡。
                if sink is not None and sink.pushed_since_reset:
                    sink.reset()
                backoff = _TRANSIENT_BACKOFF_S * attempt
                logger.warning(
                    "llm transient error (retry %s/%s after %.1fs): %s",
                    attempt, _MAX_TRANSIENT_RETRIES, backoff, exc)
            finally:
                self._sem.release()
            # 只有 transient 重試路徑會走到這（成功 return / 其他例外 raise 都已離開）。
            await asyncio.sleep(backoff)  # backoff 不佔名額,睡完下一圈重新搶

    def _call_sync(self, params: dict, timeout_s: float, *, allow_retry: bool) -> Any:
        """sync 版 _call:per-attempt 進 _sync_sem → litellm.completion → 出;
        transient 重試 backoff 在釋放名額後 time.sleep(不佔名額,避免 503 storm 放大成 busy)。
        allow_retry=False(非最後一顆)→ 一失敗立刻上拋讓 complete_sync 換家。
        num_retries=0:關掉 litellm 內部重試,避免把 timeout_s 乘上去(紅隊 B3)。"""
        attempt = 0
        while True:
            if not self._sync_sem.acquire(timeout=self._admit_timeout_s):
                raise LLMBusyError("llm concurrency saturated (sync)")
            backoff = None
            try:
                return litellm.completion(**params, timeout=timeout_s, num_retries=0)
            except litellm.Timeout:
                # 硬 deadline:逾時不 same-model 重試(重試會超出呼叫端時間預算),對齊 async _call
                # 對 asyncio.TimeoutError 的處理。非最後一顆的逾時「換家」由 complete_sync 外層決策
                # (litellm.Timeout 是 transient,remaining 有就切下一家)。
                raise
            except Exception as exc:  # noqa: BLE001 — 由 _is_transient_llm_error 分流
                if not (allow_retry and _is_transient_llm_error(exc)
                        and attempt < _MAX_TRANSIENT_RETRIES):
                    raise
                attempt += 1
                backoff = _last_model_retry_schedule()[attempt - 1]
                logger.warning(
                    "llm transient error (sync retry %s/%s after %.1fs): %s",
                    attempt, _MAX_TRANSIENT_RETRIES, backoff, exc)
            finally:
                self._sync_sem.release()
            # 只有 transient 重試路徑會走到這（成功 return / 其他例外 raise 都已離開）
            time.sleep(backoff)

    def complete_sync(self, messages, *, model, usage_type, user_id, timeout_s,
                        tools=None, temperature=None, response_format=None, api_key=None):
        """acomplete 的同步孿生:相同 fail-fast + 跨供應商 fallback + last-model 重試(共用 policy)。
        供 to_thread 內或純 sync 路徑呼叫(如 tool_calling_classifier)。
        ⚠️ 勿在 event loop 直呼(會阻塞);逾時非硬牆(靠 litellm timeout 生效階段,見 B3)。"""
        models_to_try = _plan_attempts(model)
        last_exc: BaseException | None = None
        for idx, m in enumerate(models_to_try):
            is_last = idx == len(models_to_try) - 1
            remaining = models_to_try[idx + 1:]
            params = self._build_params(messages, model=m, tools=tools, temperature=temperature,
                                        response_format=response_format, api_key=api_key)
            try:
                resp = self._call_sync(params, timeout_s, allow_retry=is_last)
            except LLMBusyError:
                raise  # 並發飽和:換家照樣飽和,直接上拋讓呼叫端降級
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if remaining and _is_transient_llm_error(exc):
                    logger.warning(
                        "naru_llm_fallback_trigger primary=%s failed_model=%s next=%s "
                        "reason=%s usage_type=%s uid=%s",
                        model, m, remaining[0], type(exc).__name__, usage_type, user_id)
                    continue
                raise
            if not resp.choices:
                raise ValueError(f"LLM empty choices (safety filter / load). model={m}")
            if idx > 0:
                logger.warning(
                    "naru_llm_fallback_success primary=%s fallback_model=%s usage_type=%s uid=%s",
                    model, m, usage_type, user_id)
            self._log_usage(m, usage_type, user_id, resp)
            return resp
        raise last_exc  # type: ignore[misc]

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
                        tools=None, temperature=None, response_format=None, api_key=None,
                        model_fallbacks=None):
        # primary model 一失敗(暫時性錯誤或逾時)就立刻切下一家(fail-fast,不原地重試燒時間);
        # 只有鏈上最後一顆(無處可切)才 same-model transient 重試當保險。fallback 觸發/成功都打 log,
        # 維運可 grep naru_llm_fallback_trigger / naru_llm_fallback_success 看是否頂上成功。
        # T-0130 案例3 修正:①gemini 過載 storm 一 503 就換 Mistral,不原地 retry 到逾時;
        # ②primary【逾時】也視同失敗換家(舊 code 逾時直接上拋 → Mistral 從沒被觸發、用戶撞 busy)。
        # model_fallbacks:呼叫端注入的 per-usage fallback(來自 agent_models.yaml),
        # 預設 None → 與改動前行為完全相同(只走 env 跨供應商 fallback)。
        # sink 只在「本 request 裝了 sink」且「這個 usage_type 允許串流」時生效。
        sink = current_delta_sink() if usage_type in STREAMABLE_USAGE_TYPES else None

        def _drop_partial() -> None:
            # 換家 = 換一個 model 重新回答,已串出去的半句與最終答案無關。
            if sink is not None and sink.pushed_since_reset:
                sink.reset()

        models_to_try = _plan_attempts(model, model_fallbacks)
        last_exc: BaseException | None = None
        # 整條 ladder 包起來:只要 acomplete 沒有帶著成功的 resp 離開(逾時無 fallback、永久錯、
        # 最後一顆重試耗盡、empty choices、CancelledError…),已串出去的半句就永遠不會被完成
        # → 用戶盯著一句斷掉的話。單點保證「非成功離開 = 先叫 client 清掉」,不必在每個 raise 前撒。
        try:
            for idx, m in enumerate(models_to_try):
                is_last = idx == len(models_to_try) - 1
                remaining = models_to_try[idx + 1:]
                params = self._build_params(messages, model=m, tools=tools, temperature=temperature,
                                            response_format=response_format, api_key=api_key)
                try:
                    # 非最後一顆 → allow_retry=False(fail-fast 換家);最後一顆 → 保留 same-model 重試。
                    resp = await self._call(params, timeout_s, allow_retry=is_last, sink=sink)
                except asyncio.CancelledError:
                    raise  # 外層硬 deadline 取消:換家也超出呼叫端總預算,直接上拋
                except LLMBusyError:
                    raise  # 並發飽和:同一 gateway semaphore,換家照樣飽和
                except asyncio.TimeoutError as exc:
                    # primary 逾時(model 太慢)= 該 model 失敗;有 fallback 就換家(A 修)。
                    last_exc = exc
                    if remaining:
                        _drop_partial()
                        logger.warning(
                            "naru_llm_fallback_trigger primary=%s failed_model=%s next=%s "
                            "reason=timeout usage_type=%s uid=%s",
                            model, m, remaining[0], usage_type, user_id)
                        continue
                    raise  # 已無 fallback → 維持逾時上拋
                except Exception as exc:  # noqa: BLE001 — 由 _is_transient_llm_error 分流
                    last_exc = exc
                    if remaining and _is_transient_llm_error(exc):
                        _drop_partial()
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
        except BaseException:
            _drop_partial()
            raise

    async def acomplete_structured(self, messages, *, model, usage_type, user_id, timeout_s, api_key=None):
        """結構化輸出：response_format={"type":"json_object"} + json.loads（寬鬆解析，
        不用 Pydantic strict —— 對齊現行寬鬆解析行為，避免回退）。"""
        resp = await self.acomplete(messages, model=model, usage_type=usage_type, user_id=user_id,
                                    timeout_s=timeout_s, response_format={"type": "json_object"}, api_key=api_key)
        content = resp.choices[0].message.content
        return json.loads(content)


# module-level singleton（--workers 1 下 per-process=per-instance 全域有效）
llm_gateway = AsyncLLMGateway()
