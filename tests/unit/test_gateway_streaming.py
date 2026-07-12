"""Gateway streaming. litellm.acompletion is monkeypatched — no real LLM calls
(cost), which is the sanctioned mock boundary for LLM providers."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from naru_agent.llm import async_gateway
from naru_agent.llm.async_gateway import AsyncLLMGateway
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


def _chunk(content=None, finish_reason=None):
    delta = SimpleNamespace(content=content)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


def _response(content="hi", finish_reason="stop"):
    msg = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=msg, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=None)


def _install_stream(monkeypatch, chunks, *, built=None, calls=None):
    async def fake_acompletion(**params):
        if calls is not None:
            calls.append(params)
        if not params.get("stream"):
            return _response()

        async def gen():
            for c in chunks:
                yield c
        return gen()

    monkeypatch.setattr(async_gateway.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(
        async_gateway.litellm, "stream_chunk_builder",
        lambda chunks_, messages=None: built or _response(),
    )


@pytest.mark.asyncio
async def test_no_sink_does_not_stream(monkeypatch):
    """Without a sink the gateway must not pass stream=True — every other
    usage_type's behaviour stays bit-for-bit identical."""
    calls: list[dict] = []
    _install_stream(monkeypatch, [], calls=calls)
    gw = AsyncLLMGateway()
    await gw.acomplete([{"role": "user", "content": "x"}], model="m",
                       usage_type="rizo_coach", user_id="u", timeout_s=5)
    assert calls and "stream" not in calls[0]


@pytest.mark.asyncio
async def test_non_streamable_usage_type_does_not_stream(monkeypatch):
    """A sink is installed but the usage_type is not rizo_coach → no streaming."""
    calls: list[dict] = []
    _install_stream(monkeypatch, [], calls=calls)
    gw = AsyncLLMGateway()
    sink = RecordingSink()
    with use_delta_sink(sink):
        await gw.acomplete([{"role": "user", "content": "x"}], model="m",
                           usage_type="rizo_compression", user_id="u", timeout_s=5)
    assert calls and "stream" not in calls[0]
    assert sink.pushes == []


@pytest.mark.asyncio
async def test_streams_deltas_and_returns_reassembled_response(monkeypatch):
    chunks = [_chunk("你"), _chunk("好"), _chunk(None, finish_reason="stop")]
    _install_stream(monkeypatch, chunks, built=_response("你好"))
    gw = AsyncLLMGateway()
    sink = RecordingSink()
    with use_delta_sink(sink):
        resp = await gw.acomplete([{"role": "user", "content": "x"}], model="m",
                                  usage_type="rizo_coach", user_id="u", timeout_s=5)
    assert sink.pushes == ["你", "好"]
    assert resp.choices[0].message.content == "你好"   # agno 拿到的與非串流時同構


@pytest.mark.asyncio
async def test_tool_calls_finish_resets_the_sink(monkeypatch):
    """agno throws away prose emitted alongside tool_calls — the client must
    not keep showing it."""
    chunks = [_chunk("讓我查"), _chunk(None, finish_reason="tool_calls")]
    _install_stream(monkeypatch, chunks,
                    built=_response("讓我查", finish_reason="tool_calls"))
    gw = AsyncLLMGateway()
    sink = RecordingSink()
    with use_delta_sink(sink):
        await gw.acomplete([{"role": "user", "content": "x"}], model="m",
                           usage_type="rizo_coach", user_id="u", timeout_s=5)
    assert sink.pushes == ["讓我查"]
    assert sink.resets == 1


@pytest.mark.asyncio
async def test_fallback_after_partial_deltas_resets_the_sink(monkeypatch):
    """primary streamed some text then died → the fallback model's answer is a
    different answer; the client must drop the orphaned partial."""
    state = {"n": 0}

    async def fake_acompletion(**params):
        state["n"] += 1
        if state["n"] == 1:
            async def bad():
                yield _chunk("半句")
                raise async_gateway.litellm.ServiceUnavailableError(
                    "overloaded", llm_provider="gemini", model="m")
            return bad()

        async def good():
            yield _chunk("完整回覆")
            yield _chunk(None, finish_reason="stop")
        return good()

    monkeypatch.setattr(async_gateway.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(async_gateway.litellm, "stream_chunk_builder",
                        lambda chunks_, messages=None: _response("完整回覆"))
    gw = AsyncLLMGateway()
    sink = RecordingSink()
    with use_delta_sink(sink):
        resp = await gw.acomplete([{"role": "user", "content": "x"}], model="m",
                                  usage_type="rizo_coach", user_id="u", timeout_s=5,
                                  model_fallbacks=["fallback-model"])
    assert sink.resets >= 1
    assert resp.choices[0].message.content == "完整回覆"
