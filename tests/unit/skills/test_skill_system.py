from __future__ import annotations

from naru_agent.skills.base import (
    BaseSkill,
    FunctionSkill,
    SkillContext,
    SkillResult,
    skill,
)
from naru_agent.skills.selectors import KeywordSkillSelector
from naru_agent.skills.registry import SkillRegistry


# ── @skill decorator ──


def test_skill_decorator_creates_function_skill():
    @skill(name="greet", triggers=["hello"], description="Greeting")
    def greet(message: str, context: SkillContext) -> str:
        return "Be friendly."

    assert isinstance(greet, FunctionSkill)
    assert greet.name == "greet"
    assert greet.triggers == ["hello"]


def test_skill_str_return_wrapped_in_skill_result():
    @skill(name="test")
    def my_skill(message: str, context: SkillContext) -> str:
        return "injected prompt"

    ctx = SkillContext(message="hi")
    result = my_skill.run("hi", ctx)
    assert isinstance(result, SkillResult)
    assert result.prompt_injection == "injected prompt"
    assert result.skill_name == "test"


def test_skill_returning_skill_result_directly():
    @skill(name="direct")
    def my_skill(message: str, context: SkillContext) -> SkillResult:
        return SkillResult(prompt_injection="custom", override_system_prompt="override")

    ctx = SkillContext(message="hi")
    result = my_skill.run("hi", ctx)
    assert result.prompt_injection == "custom"
    assert result.override_system_prompt == "override"
    assert result.skill_name == "direct"


# ── KeywordSkillSelector ──


def test_keyword_selector_matches():
    @skill(name="greet", triggers=["hello", "hi"])
    def greet(message: str, context: SkillContext) -> str:
        return ""

    @skill(name="bye", triggers=["goodbye"])
    def bye(message: str, context: SkillContext) -> str:
        return ""

    selector = KeywordSkillSelector()
    matched = selector.select([greet, bye], "Hello there!")
    assert len(matched) == 1
    assert matched[0].name == "greet"


def test_keyword_selector_case_insensitive():
    @skill(name="test", triggers=["HELLO"])
    def s(message: str, context: SkillContext) -> str:
        return ""

    matched = KeywordSkillSelector().select([s], "hello world")
    assert len(matched) == 1


def test_keyword_selector_always_active():
    @skill(name="always", always_active=True)
    def s(message: str, context: SkillContext) -> str:
        return ""

    matched = KeywordSkillSelector().select([s], "anything at all")
    assert len(matched) == 1


# ── SkillResult.skipped ──


def test_skipped_result():
    r = SkillResult(prompt_injection="something", skipped=True)
    assert r.skipped


# ── Priority sorting ──


def test_skills_sorted_by_priority():
    @skill(name="low", triggers=["x"], priority=1)
    def low(m, c):
        return "low"

    @skill(name="high", triggers=["x"], priority=10)
    def high(m, c):
        return "high"

    registry = SkillRegistry([low, high], KeywordSkillSelector())
    results = registry.run_skills("x test", SkillContext(message="x test"))
    assert len(results) == 2
    assert results[0].skill_name == "high"
    assert results[1].skill_name == "low"


# ── override_system_prompt conflict ──


def test_multiple_override_system_prompt_only_first():
    """Simulate what agent.py does: only the first override wins."""
    results = [
        SkillResult(prompt_injection="p1", override_system_prompt="override1", skill_name="s1"),
        SkillResult(prompt_injection="p2", override_system_prompt="override2", skill_name="s2"),
    ]

    dynamic_instructions = ["original system prompt"]
    _system_overridden = False
    for sr in results:
        if sr.skipped or not sr.prompt_injection:
            continue
        if sr.override_system_prompt is not None:
            if _system_overridden:
                continue
            _system_overridden = True
            dynamic_instructions[0] = sr.override_system_prompt
        else:
            dynamic_instructions.append(sr.prompt_injection)

    assert dynamic_instructions == ["override1"]


# ── SkillContext.get_knowledge ──


def test_get_knowledge_no_store():
    ctx = SkillContext(message="test", knowledge_store=None)
    assert ctx.get_knowledge("query") == ""


def test_get_knowledge_with_store():
    class FakeResult:
        def __init__(self, content):
            self.content = content

    class FakeStore:
        def search(self, query, top_k=3):
            return [FakeResult("chunk1"), FakeResult("chunk2")]

    ctx = SkillContext(message="test", knowledge_store=FakeStore())
    assert ctx.get_knowledge("query") == "chunk1\nchunk2"


# ── Registry parallel execution ──


def test_registry_run_skills_parallel():
    import time

    @skill(name="slow1", triggers=["go"], priority=1)
    def slow1(m, c):
        time.sleep(0.1)
        return "result1"

    @skill(name="slow2", triggers=["go"], priority=2)
    def slow2(m, c):
        time.sleep(0.1)
        return "result2"

    registry = SkillRegistry([slow1, slow2], KeywordSkillSelector())
    t0 = time.perf_counter()
    results = registry.run_skills("go now", SkillContext(message="go now"))
    elapsed = time.perf_counter() - t0

    assert len(results) == 2
    # Parallel should be < 0.2s (sequential would be >= 0.2s)
    assert elapsed < 0.19
    # Sorted by priority
    assert results[0].skill_name == "slow2"
