"""Gateway streaming.

Mock boundary = the LLM provider only: `litellm.acompletion` is monkeypatched
(cost). Everything downstream of it — including litellm's own
`stream_chunk_builder` reassembly — runs for real, on real
`ModelResponseStream` / `StreamingChoices` / `Delta` objects, exactly as the
provider emits them (trailing usage-only chunk included, because we ask for
`stream_options={"include_usage": True}`).

Faking `stream_chunk_builder` is what let the tool_calls reset ship dead: a
hand-built `finish_reason="tool_calls"` is a fiction — real litellm hands back
`"stop"` for that same chunk stream, because the trailing usage chunk's choices
are NOT empty and clobber the finish_reason.
"""
from __future__ import annotations

import pytest
from litellm.types.utils import (ChatCompletionDeltaToolCall, Delta, Function,
                                 ModelResponseStream, StreamingChoices, Usage)

from naru_agent.llm import async_gateway
from naru_agent.llm.async_gateway import AsyncLLMGateway, StreamReassemblyError
from naru_agent.llm.delta_sink import use_delta_sink


class RecordingSink:
    def __init__(self):
        self.pushes: list[str] = []
        self.resets = 0
        self._since = False

    def push(self, text: str) -> None:
        self.pushes.append(text)
        self._since = True

    def reset(self) -> None:
        self.resets += 1
        self._since = False

    @property
    def pushed_since_reset(self) -> bool:
        return self._since


# --- real litellm stream objects (what the provider actually yields) ---------

def text_chunk(content: str) -> ModelResponseStream:
    return ModelResponseStream(choices=[StreamingChoices(
        index=0, delta=Delta(content=content, role="assistant"), finish_reason=None)])


def tool_call_chunk(name: str = "get_weekly_mileage") -> ModelResponseStream:
    tc = ChatCompletionDeltaToolCall(
        id="call_1", type="function", index=0,
        function=Function(name=name, arguments='{"weeks": 1}'))
    return ModelResponseStream(choices=[StreamingChoices(
        index=0, delta=Delta(content=None, tool_calls=[tc]), finish_reason=None)])


def finish_chunk(reason: str = "stop") -> ModelResponseStream:
    return ModelResponseStream(choices=[StreamingChoices(
        index=0, delta=Delta(content=None), finish_reason=reason)])


def usage_chunk(total: int = 150) -> ModelResponseStream:
    """The trailing chunk litellm appends for stream_options={"include_usage": True}.

    Its `choices` is NOT empty — that is precisely what clobbers finish_reason.
    """
    chunk = ModelResponseStream(choices=[StreamingChoices(
        index=0, delta=Delta(content=None), finish_reason=None)])
    chunk.usage = Usage(prompt_tokens=120, completion_tokens=total - 120, total_tokens=total)
    return chunk


class FakeStream:
    """Stand-in for litellm's CustomStreamWrapper: async-iterable + aclose()."""

    def __init__(self, chunks, raise_after=None):
        self._chunks = chunks
        self._raise_after = raise_after
        self.closed = 0

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for c in self._chunks:
            yield c
        if self._raise_after is not None:
            raise self._raise_after

    async def aclose(self):
        self.closed += 1


def install_provider(monkeypatch, streams, *, calls=None, non_stream_response=None):
    """Fake ONLY the provider call. `streams` = one FakeStream per acompletion call."""
    queue = list(streams)

    async def fake_acompletion(**params):
        if calls is not None:
            calls.append(params)
        if not params.get("stream"):
            return non_stream_response or _plain_response()
        return queue.pop(0)

    monkeypatch.setattr(async_gateway.litellm, "acompletion", fake_acompletion)


def _plain_response():
    from litellm.types.utils import Choices, Message, ModelResponse
    return ModelResponse(
        choices=[Choices(message=Message(content="hi", role="assistant"), finish_reason="stop")],
        usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2))


# --- non-streaming usage_types stay bit-for-bit unchanged --------------------

@pytest.mark.asyncio
async def test_no_sink_does_not_stream(monkeypatch):
    """Without a sink the gateway must not pass stream=True — every other
    usage_type's behaviour stays bit-for-bit identical."""
    calls: list[dict] = []
    install_provider(monkeypatch, [], calls=calls)
    gw = AsyncLLMGateway()
    await gw.acomplete([{"role": "user", "content": "x"}], model="m",
                       usage_type="rizo_coach", user_id="u", timeout_s=5)
    assert calls and "stream" not in calls[0]


@pytest.mark.asyncio
async def test_non_streamable_usage_type_does_not_stream(monkeypatch):
    """A sink is installed but the usage_type is not rizo_coach → no streaming."""
    calls: list[dict] = []
    install_provider(monkeypatch, [], calls=calls)
    gw = AsyncLLMGateway()
    sink = RecordingSink()
    with use_delta_sink(sink):
        await gw.acomplete([{"role": "user", "content": "x"}], model="m",
                           usage_type="rizo_compression", user_id="u", timeout_s=5)
    assert calls and "stream" not in calls[0]
    assert sink.pushes == []


# --- happy path -------------------------------------------------------------

@pytest.mark.asyncio
async def test_streams_deltas_and_returns_reassembled_response(monkeypatch):
    stream = FakeStream([text_chunk("你"), text_chunk("好"), finish_chunk("stop"),
                         usage_chunk()])
    install_provider(monkeypatch, [stream])
    gw = AsyncLLMGateway()
    sink = RecordingSink()
    with use_delta_sink(sink):
        resp = await gw.acomplete([{"role": "user", "content": "x"}], model="m",
                                  usage_type="rizo_coach", user_id="u", timeout_s=5)
    assert sink.pushes == ["你", "好"]
    assert sink.resets == 0
    # agno 拿到的與非串流時同構(真 stream_chunk_builder 重組)
    assert resp.choices[0].message.content == "你好"
    assert resp.choices[0].finish_reason == "stop"
    assert stream.closed == 1


@pytest.mark.asyncio
async def test_streamed_response_carries_real_usage_numbers(monkeypatch):
    """_log_usage must not silently go blank for rizo_coach: the reassembled
    response has to carry the provider's real token counts (that's why we ask
    for stream_options={"include_usage": True})."""
    install_provider(monkeypatch, [FakeStream(
        [text_chunk("嗨"), finish_chunk("stop"), usage_chunk(total=150)])])
    gw = AsyncLLMGateway()
    with use_delta_sink(RecordingSink()):
        resp = await gw.acomplete([{"role": "user", "content": "x"}], model="m",
                                  usage_type="rizo_coach", user_id="u", timeout_s=5)
    assert resp.usage.total_tokens == 150
    assert resp.usage.prompt_tokens == 120


# --- Critical 1: tool_calls reset, with the real trailing usage chunk --------

@pytest.mark.asyncio
async def test_tool_calls_finish_resets_the_sink(monkeypatch):
    """agno throws away prose emitted alongside tool_calls — the client must not
    keep showing it.

    Regression guard: the trailing usage chunk makes real stream_chunk_builder
    report finish_reason="stop" even though the turn really is a tool_calls turn.
    Keying the reset off finish_reason alone is dead code in production.
    """
    install_provider(monkeypatch, [FakeStream([
        text_chunk("讓我先查一下你的跑量"),
        tool_call_chunk(),
        finish_chunk("tool_calls"),
        usage_chunk(),
    ])])
    gw = AsyncLLMGateway()
    sink = RecordingSink()
    with use_delta_sink(sink):
        resp = await gw.acomplete([{"role": "user", "content": "這週跑量多少"}], model="m",
                                  usage_type="rizo_coach", user_id="u", timeout_s=5)
    assert sink.pushes == ["讓我先查一下你的跑量"]
    assert sink.resets == 1
    assert resp.choices[0].message.tool_calls  # 真的是 tool-call 輪
    # 這行釘住 bug 本體:真 litellm 會把 finish_reason 蓋成 stop,所以它不能當判準
    assert resp.choices[0].finish_reason == "stop"


@pytest.mark.asyncio
async def test_tool_call_without_prose_does_not_reset(monkeypatch):
    """A tool-call turn that streamed nothing must not emit a spurious
    'clear the bubble' to a client that has nothing to clear."""
    install_provider(monkeypatch, [FakeStream([
        tool_call_chunk(), finish_chunk("tool_calls"), usage_chunk()])])
    gw = AsyncLLMGateway()
    sink = RecordingSink()
    with use_delta_sink(sink):
        await gw.acomplete([{"role": "user", "content": "x"}], model="m",
                           usage_type="rizo_coach", user_id="u", timeout_s=5)
    assert sink.pushes == []
    assert sink.resets == 0


# --- Important 3: partial text is never orphaned -----------------------------

@pytest.mark.asyncio
async def test_fallback_after_partial_deltas_resets_the_sink(monkeypatch):
    """primary streamed some text then died → the fallback model's answer is a
    different answer; the client must drop the orphaned partial."""
    streams = [
        FakeStream([text_chunk("半句")], raise_after=async_gateway.litellm.ServiceUnavailableError(
            "overloaded", llm_provider="gemini", model="m")),
        FakeStream([text_chunk("完整回覆"), finish_chunk("stop"), usage_chunk()]),
    ]
    install_provider(monkeypatch, streams)
    gw = AsyncLLMGateway()
    sink = RecordingSink()
    with use_delta_sink(sink):
        resp = await gw.acomplete([{"role": "user", "content": "x"}], model="m",
                                  usage_type="rizo_coach", user_id="u", timeout_s=5,
                                  model_fallbacks=["fallback-model"])
    assert sink.pushes == ["半句", "完整回覆"]   # 兩通都串了
    assert sink.resets == 1                      # 壞掉那通的半句被清掉
    assert resp.choices[0].message.content == "完整回覆"
    assert all(s.closed == 1 for s in streams)   # 兩條 stream 都關了


@pytest.mark.asyncio
async def test_terminal_failure_with_no_fallback_drops_the_partial(monkeypatch):
    """單一 model 設定:串了半句 → 503 → same-model 重試耗盡 → 例外上拋。
    例外會傳到呼叫端,但用戶手上不能留一句永遠不會被完成的話。"""
    monkeypatch.setattr(async_gateway, "_TRANSIENT_BACKOFF_S", 0.0)
    boom = async_gateway.litellm.ServiceUnavailableError(
        "overloaded", llm_provider="gemini", model="m")
    streams = [FakeStream([text_chunk("你這週的重點是")], raise_after=boom) for _ in range(3)]
    install_provider(monkeypatch, streams)
    gw = AsyncLLMGateway()
    sink = RecordingSink()
    with use_delta_sink(sink), pytest.raises(async_gateway.litellm.ServiceUnavailableError):
        await gw.acomplete([{"role": "user", "content": "x"}], model="m",
                           usage_type="rizo_coach", user_id="u", timeout_s=5)
    assert sink.pushes == ["你這週的重點是"] * 3
    assert not sink.pushed_since_reset          # 上拋前半句一定被清掉
    assert all(s.closed == 1 for s in streams)  # Important 4:中途炸掉也要關 stream


@pytest.mark.asyncio
async def test_timeout_with_no_fallback_drops_the_partial_and_closes_stream(monkeypatch):
    """逾時(wait_for 取消 async for)且無 fallback → 上拋,但 partial 要清、stream 要關。"""
    import asyncio as _asyncio

    class HangingStream(FakeStream):
        async def _gen(self):
            yield text_chunk("開始跑之前")
            await _asyncio.sleep(10)

    stream = HangingStream([])
    install_provider(monkeypatch, [stream])
    gw = AsyncLLMGateway()
    sink = RecordingSink()
    with use_delta_sink(sink), pytest.raises(_asyncio.TimeoutError):
        await gw.acomplete([{"role": "user", "content": "x"}], model="m",
                           usage_type="rizo_coach", user_id="u", timeout_s=0.05)
    assert sink.pushes == ["開始跑之前"]
    assert not sink.pushed_since_reset
    assert stream.closed == 1


# --- Minor: a reassembly bug must fail fast, not burn a fallback provider ----

@pytest.mark.asyncio
async def test_reassembly_failure_is_not_treated_as_transient(monkeypatch):
    """stream_chunk_builder 內部失敗會被 litellm 包成 APIError(status_code=500),
    那會被判成 transient → 白燒一次 LLM 呼叫 + 一顆 fallback 供應商去重跑我方的 bug。"""
    calls: list[dict] = []
    install_provider(monkeypatch, [FakeStream([text_chunk("嗨"), finish_chunk("stop")])],
                     calls=calls)

    def boom(chunks_, messages=None):
        raise async_gateway.litellm.APIError(
            status_code=500, message="reassembly bug", llm_provider="litellm", model="m")

    monkeypatch.setattr(async_gateway.litellm, "stream_chunk_builder", boom)
    gw = AsyncLLMGateway()
    sink = RecordingSink()
    with use_delta_sink(sink), pytest.raises(StreamReassemblyError):
        await gw.acomplete([{"role": "user", "content": "x"}], model="m",
                           usage_type="rizo_coach", user_id="u", timeout_s=5,
                           model_fallbacks=["fallback-model"])
    assert len(calls) == 1                 # fallback 沒被燒掉
    assert not sink.pushed_since_reset     # 半句也清掉了
