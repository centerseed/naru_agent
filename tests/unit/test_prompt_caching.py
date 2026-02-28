"""Tests for prompt caching support in LiteLLMProvider and Runner._accumulate_usage."""

from __future__ import annotations

from naru_agent.llm.litellm_provider import LiteLLMProvider
from naru_agent.runner import Runner


class TestApplyCacheControl:
    def test_system_message_converted_to_content_block(self):
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
        ]
        result = LiteLLMProvider._apply_cache_control(messages)

        assert result[0]["role"] == "system"
        assert isinstance(result[0]["content"], list)
        assert result[0]["content"][0] == {
            "type": "text",
            "text": "You are a helpful assistant.",
            "cache_control": {"type": "ephemeral"},
        }
        # User message should be untouched
        assert result[1] == {"role": "user", "content": "Hello"}

    def test_already_block_format_gets_cache_control(self):
        messages = [
            {"role": "system", "content": [{"type": "text", "text": "System prompt"}]},
        ]
        result = LiteLLMProvider._apply_cache_control(messages)
        assert result[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert result[0]["content"][0]["text"] == "System prompt"

    def test_non_system_messages_unchanged(self):
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]
        result = LiteLLMProvider._apply_cache_control(messages)
        assert result == messages

    def test_enable_cache_false_skips_transform(self):
        provider = LiteLLMProvider(model="anthropic/claude-sonnet-4-20250514", enable_cache=False)
        assert provider._should_apply_cache() is False

    def test_cache_only_applied_to_anthropic_models(self):
        # Gemini — should NOT apply even with enable_cache=True
        gemini = LiteLLMProvider(model="gemini/gemini-2.5-flash-lite", enable_cache=True)
        assert gemini._should_apply_cache() is False

        # OpenAI — should NOT apply
        openai = LiteLLMProvider(model="gpt-4o", enable_cache=True)
        assert openai._should_apply_cache() is False

        # Anthropic — should apply
        claude = LiteLLMProvider(model="anthropic/claude-sonnet-4-20250514", enable_cache=True)
        assert claude._should_apply_cache() is True

        # Claude shorthand — should apply
        claude2 = LiteLLMProvider(model="claude-sonnet-4-20250514", enable_cache=True)
        assert claude2._should_apply_cache() is True


class TestExtractUsage:
    def test_basic_usage(self):
        class FakeUsage:
            prompt_tokens = 100
            completion_tokens = 50
            total_tokens = 150

        result = LiteLLMProvider._extract_usage(FakeUsage())
        assert result == {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }

    def test_cache_fields_extracted(self):
        class FakeUsage:
            prompt_tokens = 100
            completion_tokens = 50
            total_tokens = 150
            cache_creation_input_tokens = 80
            cache_read_input_tokens = 20

        result = LiteLLMProvider._extract_usage(FakeUsage())
        assert result["cache_creation_input_tokens"] == 80
        assert result["cache_read_input_tokens"] == 20

    def test_prompt_tokens_details_extracted(self):
        class FakeDetails:
            def __init__(self):
                self.cached_tokens = 60

        class FakeUsage:
            prompt_tokens = 100
            completion_tokens = 50
            total_tokens = 150
            cache_creation_input_tokens = None
            cache_read_input_tokens = None
            prompt_tokens_details = FakeDetails()

        result = LiteLLMProvider._extract_usage(FakeUsage())
        assert result["prompt_tokens_details"] == {"cached_tokens": 60}

    def test_no_cache_fields_when_absent(self):
        class FakeUsage:
            prompt_tokens = 100
            completion_tokens = 50
            total_tokens = 150

        result = LiteLLMProvider._extract_usage(FakeUsage())
        assert "cache_creation_input_tokens" not in result
        assert "cache_read_input_tokens" not in result
        assert "prompt_tokens_details" not in result


class TestAccumulateUsageNested:
    def test_flat_accumulation(self):
        total: dict = {}
        Runner._accumulate_usage(total, {"prompt_tokens": 10, "completion_tokens": 5})
        Runner._accumulate_usage(total, {"prompt_tokens": 20, "completion_tokens": 15})
        assert total == {"prompt_tokens": 30, "completion_tokens": 20}

    def test_nested_dict_accumulation(self):
        total: dict = {}
        Runner._accumulate_usage(total, {
            "prompt_tokens": 100,
            "prompt_tokens_details": {"cached_tokens": 60},
        })
        Runner._accumulate_usage(total, {
            "prompt_tokens": 50,
            "prompt_tokens_details": {"cached_tokens": 30},
        })
        assert total == {
            "prompt_tokens": 150,
            "prompt_tokens_details": {"cached_tokens": 90},
        }

    def test_mixed_keys(self):
        total: dict = {}
        Runner._accumulate_usage(total, {
            "prompt_tokens": 100,
            "cache_creation_input_tokens": 80,
            "prompt_tokens_details": {"cached_tokens": 60},
        })
        Runner._accumulate_usage(total, {
            "prompt_tokens": 50,
            "completion_tokens": 25,
            "prompt_tokens_details": {"cached_tokens": 40},
        })
        assert total == {
            "prompt_tokens": 150,
            "cache_creation_input_tokens": 80,
            "completion_tokens": 25,
            "prompt_tokens_details": {"cached_tokens": 100},
        }
