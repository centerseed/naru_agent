"""Tests for AgentPipeline — sequential pipeline primitive."""

from unittest.mock import MagicMock

import pytest

from naru_agent.agent import NaruResult
from naru_agent.orchestration.pipeline import AgentPipeline


def _make_delegate(content: str) -> MagicMock:
    """Create a mock delegate that returns a NaruResult with given content."""
    delegate = MagicMock()
    delegate.chat.return_value = NaruResult(content=content)
    return delegate


def _make_echo_delegate() -> MagicMock:
    """Create a mock delegate that echoes the input with a prefix."""
    delegate = MagicMock()
    delegate.chat.side_effect = lambda msg, **kw: NaruResult(content=f"[processed] {msg}")
    return delegate


class TestPipelineTwoStages:
    """B receives A's content as its input message."""

    def test_second_stage_receives_first_output(self):
        stage_a = _make_delegate("research result")
        stage_b = MagicMock()
        stage_b.chat.return_value = NaruResult(content="summary of research result")

        pipeline = AgentPipeline([stage_a, stage_b])
        result = pipeline.chat("original question")

        stage_a.chat.assert_called_once_with("original question", user_id=None, session_id=None)
        stage_b.chat.assert_called_once_with("research result", user_id=None, session_id=None)
        assert result.content == "summary of research result"

    def test_three_stages_chain(self):
        stage_a = _make_delegate("step1")
        stage_b = MagicMock()
        stage_b.chat.return_value = NaruResult(content="step2")
        stage_c = MagicMock()
        stage_c.chat.return_value = NaruResult(content="step3")

        pipeline = AgentPipeline([stage_a, stage_b, stage_c])
        result = pipeline.chat("input")

        stage_b.chat.assert_called_once_with("step1", user_id=None, session_id=None)
        stage_c.chat.assert_called_once_with("step2", user_id=None, session_id=None)
        assert result.content == "step3"


class TestPipelineSingleStage:
    """Single stage = passthrough."""

    def test_single_stage_passthrough(self):
        delegate = _make_echo_delegate()
        pipeline = AgentPipeline([delegate])
        result = pipeline.chat("hello")

        delegate.chat.assert_called_once()
        assert result.content == "[processed] hello"


class TestPipelineEmptyRaises:
    """Empty stages list should raise ValueError."""

    def test_empty_stages_raises(self):
        with pytest.raises(ValueError, match="at least one stage"):
            AgentPipeline([])


class TestPipelinePreservesUserIdSessionId:
    """user_id and session_id are forwarded to every stage."""

    def test_user_id_session_id_forwarded(self):
        stage_a = _make_delegate("a")
        stage_b = _make_delegate("b")

        pipeline = AgentPipeline([stage_a, stage_b])
        pipeline.chat("msg", user_id="u1", session_id="s1")

        stage_a.chat.assert_called_once_with("msg", user_id="u1", session_id="s1")
        stage_b.chat.assert_called_once_with("a", user_id="u1", session_id="s1")


class TestPipelineReturnsLastResult:
    """The final NaruResult object (not just content) is returned."""

    def test_returns_full_result_from_last_stage(self):
        stage_a = _make_delegate("a")
        last_result = NaruResult(content="final", usage={"total": 42}, session_id="s1")
        stage_b = MagicMock()
        stage_b.chat.return_value = last_result

        pipeline = AgentPipeline([stage_a, stage_b])
        result = pipeline.chat("input")

        assert result is last_result
        assert result.usage == {"total": 42}


class TestPipelineAsDelegate:
    """Pipeline satisfies AgentChatDelegate and can be used as a delegate."""

    def test_satisfies_delegate_protocol(self):
        pipeline = AgentPipeline([_make_delegate("x")])
        assert hasattr(pipeline, "chat")
        assert callable(pipeline.chat)

    def test_name_attribute(self):
        pipeline = AgentPipeline([_make_delegate("x")], name="my_pipeline")
        assert pipeline.name == "my_pipeline"

    def test_default_name(self):
        pipeline = AgentPipeline([_make_delegate("x")])
        assert pipeline.name == "pipeline"
