from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from naru_agent.skills.base import SkillContext, skill
from naru_agent.skills.selectors import LLMSkillSelector


# ── Helpers ──


def _make_calendar_skill():
    @skill(
        name="calendar",
        description="Query calendar events",
        triggers=["calendar", "行事曆"],
        trigger_conditions=["用戶想查詢行事曆、問某天有什麼行程"],
        exclusion_conditions=["用戶只是提到日期但意圖是記錄或交辦，不是查行事曆"],
    )
    def calendar(message: str, context: SkillContext) -> str:
        return "calendar context"

    return calendar


def _make_reminder_skill():
    @skill(
        name="reminder",
        description="Set reminders",
        triggers=["remind", "reminder"],
    )
    def reminder(message: str, context: SkillContext) -> str:
        return "reminder context"

    return reminder


def _make_always_active_skill():
    @skill(name="always", always_active=True, description="Always on")
    def always(message: str, context: SkillContext) -> str:
        return "always context"

    return always


# ── Tests ──


def test_llm_selector_matches_trigger_conditions():
    """chat_fn returns ['calendar'], verify calendar skill is selected."""
    calendar = _make_calendar_skill()
    reminder = _make_reminder_skill()
    chat_fn = MagicMock(return_value='["calendar"]')

    selector = LLMSkillSelector(chat_fn=chat_fn)
    result = selector.select([calendar, reminder], "星期三有什麼行程？")

    assert len(result) == 1
    assert result[0].name == "calendar"
    chat_fn.assert_called_once()


def test_llm_selector_excludes_by_exclusion_conditions():
    """chat_fn returns [] (message matches exclusion condition), verify no skill selected."""
    calendar = _make_calendar_skill()
    chat_fn = MagicMock(return_value="[]")

    selector = LLMSkillSelector(chat_fn=chat_fn)
    result = selector.select([calendar], "星期三要開會（記錄一下）")

    assert result == []
    chat_fn.assert_called_once()


def test_llm_selector_always_active_included():
    """always_active skill is not sent to LLM but is always included in result."""
    calendar = _make_calendar_skill()
    always = _make_always_active_skill()
    chat_fn = MagicMock(return_value='["calendar"]')

    selector = LLMSkillSelector(chat_fn=chat_fn)
    result = selector.select([calendar, always], "查行事曆")

    names = {s.name for s in result}
    assert "always" in names
    assert "calendar" in names
    # Prompt must not include always_active skill
    prompt_arg = chat_fn.call_args[0][0]
    assert "always" not in prompt_arg


def test_llm_selector_empty_candidates():
    """When all skills are always_active, chat_fn should not be called."""
    always1 = _make_always_active_skill()
    chat_fn = MagicMock()

    selector = LLMSkillSelector(chat_fn=chat_fn)
    result = selector.select([always1], "any message")

    assert len(result) == 1
    assert result[0].name == "always"
    chat_fn.assert_not_called()


def test_llm_selector_fallback_to_triggers():
    """Skill without trigger_conditions should have triggers listed in the prompt."""
    reminder = _make_reminder_skill()  # no trigger_conditions
    chat_fn = MagicMock(return_value="[]")

    selector = LLMSkillSelector(chat_fn=chat_fn)
    selector.select([reminder], "set a reminder")

    prompt = chat_fn.call_args[0][0]
    assert "remind" in prompt  # triggers fallback visible in prompt


def test_llm_selector_parse_response_json():
    """Normal JSON array response is parsed correctly."""
    calendar = _make_calendar_skill()
    reminder = _make_reminder_skill()
    chat_fn = MagicMock(return_value='["calendar", "reminder"]')

    selector = LLMSkillSelector(chat_fn=chat_fn)
    result = selector.select([calendar, reminder], "查行事曆並設提醒")

    names = {s.name for s in result}
    assert "calendar" in names
    assert "reminder" in names


def test_llm_selector_parse_response_with_extra_text():
    """Response containing extra text around JSON array uses regex fallback."""
    calendar = _make_calendar_skill()
    chat_fn = MagicMock(
        return_value='Sure! Based on the message, the skills to activate are: ["calendar"].'
    )

    selector = LLMSkillSelector(chat_fn=chat_fn)
    result = selector.select([calendar], "查行事曆")

    assert len(result) == 1
    assert result[0].name == "calendar"


def test_llm_selector_builds_correct_prompt():
    """Prompt includes trigger_conditions and exclusion_conditions text."""
    calendar = _make_calendar_skill()
    chat_fn = MagicMock(return_value="[]")

    selector = LLMSkillSelector(chat_fn=chat_fn)
    selector.select([calendar], "test message")

    prompt = chat_fn.call_args[0][0]
    assert "trigger_conditions" in prompt
    assert "exclusion_conditions" in prompt
    assert "用戶想查詢行事曆" in prompt
    assert "用戶只是提到日期" in prompt
    assert "test message" in prompt


def test_llm_selector_parse_response_empty_array():
    """Empty JSON array results in no skills selected."""
    calendar = _make_calendar_skill()
    chat_fn = MagicMock(return_value="[]")

    selector = LLMSkillSelector(chat_fn=chat_fn)
    result = selector.select([calendar], "irrelevant message")

    assert result == []


def test_llm_selector_parse_response_malformed_fallback():
    """Malformed response falls back to quoted string extraction."""
    calendar = _make_calendar_skill()
    chat_fn = MagicMock(return_value='Activate "calendar" for this.')

    selector = LLMSkillSelector(chat_fn=chat_fn)
    result = selector.select([calendar], "查行事曆")

    assert len(result) == 1
    assert result[0].name == "calendar"
