"""Context compression integration test.

Verifies the full NaruAgent.chat() → background compression → summary injection path.

Execution:
    GEMINI_API_KEY=xxx pytest tests/integration/test_context_compression.py -v --tb=short -x
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from naru_agent.agent import NaruAgent

pytestmark = pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set",
)

MODEL = os.getenv("CHAT_AGENT_MODEL", "gemini/gemini-2.5-flash-lite")
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", "gemini/gemma-3-12b-it")


def _drain_bg(agent: NaruAgent):
    """Shutdown bg executor and recreate it, ensuring all pending tasks complete."""
    agent._bg_executor.shutdown(wait=True)
    agent._bg_executor = ThreadPoolExecutor(max_workers=2)


class TestContextCompression:
    """Full chat() path integration tests for context compression."""

    def _make_agent(self, threshold=3, keep_last=3):
        return NaruAgent(
            model=MODEL,
            instructions=["You are a helpful assistant. Reply concisely."],
            add_history_to_context=True,
            context_compression=True,
            summary_model=SUMMARY_MODEL,
            compression_threshold_rounds=threshold,
            compression_keep_last_rounds=keep_last,
        )

    def test_compression_triggers_after_threshold(self):
        """Compression should trigger when total_runs > threshold."""
        agent = self._make_agent(threshold=3, keep_last=3)
        sid = "test-trigger"

        # Rounds 1-3: below threshold, no compression
        for i in range(3):
            agent.chat(f"Question {i+1}: What is {i+1}+{i+1}?", session_id=sid)
        _drain_bg(agent)

        summary = agent._context_compressor.get_summary_sync(sid)
        assert summary is None, "Should not compress at or below threshold"

        # Round 4: triggers compression (4 > 3)
        agent.chat("Question 4: What is 4+4?", session_id=sid)
        _drain_bg(agent)

        summary = agent._context_compressor.get_summary_sync(sid)
        assert summary is not None, "Should compress after exceeding threshold"
        assert summary.compressed_through_run == 1  # 4 - 3 = 1
        assert len(summary.summary_text) > 0

    def test_summary_injected_into_instructions(self):
        """After compression, subsequent rounds should include summary in context."""
        agent = self._make_agent(threshold=3, keep_last=3)
        sid = "test-inject"

        # Build up 4 rounds to trigger compression
        topics = [
            "Tell me about cats",
            "Tell me about dogs",
            "Tell me about birds",
            "Tell me about fish",  # triggers background compression
        ]
        for msg in topics:
            agent.chat(msg, session_id=sid)
        _drain_bg(agent)

        # Verify summary exists
        summary = agent._context_compressor.get_summary_sync(sid)
        assert summary is not None

        # Round 5: summary should be injected into dynamic_instructions
        result = agent.chat(
            "Based on our entire conversation, what was the first animal I asked about?",
            session_id=sid,
        )
        assert result.content, "Response should not be empty"

    def test_num_history_runs_auto_aligned(self):
        """When context_compression=True, num_history_runs should auto-align to keep_last_rounds."""
        agent = self._make_agent(threshold=3, keep_last=5)

        # Force agent creation by doing one chat
        agent.chat("Hello", session_id="test-align")

        assert agent._agno_agent is not None
        assert agent.num_history_runs == 5

    def test_summary_accumulates_across_rounds(self):
        """Summary should cover more runs as conversation grows."""
        agent = self._make_agent(threshold=3, keep_last=3)
        sid = "test-accumulate"

        # 5 rounds
        for i in range(5):
            agent.chat(f"Round {i+1} message", session_id=sid)
        _drain_bg(agent)

        summary_after_5 = agent._context_compressor.get_summary_sync(sid)
        assert summary_after_5 is not None
        run_5 = summary_after_5.compressed_through_run  # should be 2

        # 3 more rounds (total 8)
        for i in range(5, 8):
            agent.chat(f"Round {i+1} message", session_id=sid)
        _drain_bg(agent)

        summary_after_8 = agent._context_compressor.get_summary_sync(sid)
        assert summary_after_8 is not None
        assert summary_after_8.compressed_through_run > run_5

    def test_compression_timing(self):
        """Background compression should complete within reasonable time."""
        agent = self._make_agent(threshold=3, keep_last=3)
        sid = "test-timing"

        for i in range(4):
            agent.chat(f"Message {i+1}", session_id=sid)

        t0 = time.perf_counter()
        _drain_bg(agent)
        bg_wait = time.perf_counter() - t0

        summary = agent._context_compressor.get_summary_sync(sid)
        assert summary is not None
        # Background compression (Gemma 12B) should finish within 15s
        assert bg_wait < 15.0, f"Background compression took too long: {bg_wait:.1f}s"
        print(f"\nBackground compression wait: {bg_wait:.2f}s")
        print(f"Summary model: {summary.model_used}")
        print(f"Summary length: {len(summary.summary_text)} chars")
