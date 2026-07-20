from __future__ import annotations

from types import SimpleNamespace

import pytest

from naru_agent.llm.async_gateway import AsyncLLMGateway
from naru_agent.llm.attempt_observer import use_attempt_observer


class _Unavailable(RuntimeError):
    status_code = 503


def _response():
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
    )


@pytest.mark.asyncio
async def test_observer_records_every_physical_fallback_attempt_without_content(monkeypatch):
    gateway = AsyncLLMGateway()
    calls = []

    async def completion(params, sink):
        del sink
        calls.append(params["model"])
        if params["model"] == "gemini/primary":
            raise _Unavailable("overloaded")
        return _response()

    monkeypatch.setattr(gateway, "_acompletion", completion)
    observations = []
    with use_attempt_observer(observations.append):
        response = await gateway.acomplete(
            [{"role": "user", "content": "private text"}],
            model="gemini/primary",
            model_fallbacks=["mistral/fallback"],
            usage_type="rizo_coach",
            user_id="private-user",
            timeout_s=1,
        )

    assert response.choices
    assert calls == ["gemini/primary", "mistral/fallback"]
    assert [(item.provider, item.model, item.outcome) for item in observations] == [
        ("gemini", "primary", "retryable_error"),
        ("mistral", "fallback", "success"),
    ]
    assert observations[0].fallback_reason == "unavailable"
    assert observations[1].input_tokens == 11
    assert observations[1].output_tokens == 7
    assert all(not hasattr(item, "messages") for item in observations)


@pytest.mark.asyncio
async def test_last_model_retries_are_each_visible_to_the_audit_observer(monkeypatch):
    gateway = AsyncLLMGateway()
    calls = 0

    async def completion(params, sink):
        nonlocal calls
        del params, sink
        calls += 1
        if calls < 3:
            raise _Unavailable("overloaded")
        return _response()

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(gateway, "_acompletion", completion)
    monkeypatch.setattr("naru_agent.llm.async_gateway.asyncio.sleep", no_sleep)
    observations = []
    with use_attempt_observer(observations.append):
        await gateway.acomplete(
            [{"role": "user", "content": "x"}],
            model="mistral/fallback",
            usage_type="rizo_coach",
            user_id="user",
            timeout_s=1,
        )

    assert calls == 3
    assert [item.outcome for item in observations] == [
        "retryable_error", "retryable_error", "success",
    ]
