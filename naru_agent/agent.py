from __future__ import annotations

import asyncio
import logging
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from naru_agent.tracing.trace import Trace

from pydantic import BaseModel, Field

from naru_agent.guardrails.base import BaseGuardrail, GuardrailResult
from naru_agent.intent.base import BaseIntentClassifier, IntentResult
from naru_agent.intent.tool_calling_classifier import BaseToolCallingClassifier
from naru_agent.knowledge.base import BaseKnowledgeStore
from naru_agent.llm.base import BaseLLM

from agno.agent import Agent as AgnoAgent
from agno.models.litellm import LiteLLM as AgnoLiteLLM
from naru_agent.tools.base import BaseTool

logger = logging.getLogger(__name__)

# Appended to the empty-content fallback so the model answers from the tool
# results + injected context instead of echoing the user's question verbatim.
_FALLBACK_ANSWER_DIRECTIVE = (
    "請根據上面的工具結果與已提供的脈絡，直接用一段話回答我最初的問題。"
    "不要重複或改寫我的問題；若某項資料查不到，就用脈絡裡已有的資訊誠實回答"
    "（例如今天還沒有訓練紀錄就直說、並可提到今天計畫的課表），不要把問題丟回給我。"
)


class _GatewayLiteLLM(AgnoLiteLLM):
    """Agno LiteLLM adapter whose async calls use the shared Naru gateway."""

    gateway_usage_type: str = "rizo_chat"
    gateway_user_id: str = ""
    gateway_timeout_s: float = 30.0

    async def ainvoke(
        self,
        messages,
        assistant_message,
        response_format=None,
        tools=None,
        tool_choice=None,
        run_response=None,
        compress_tool_results: bool = False,
    ):
        from naru_agent.llm.async_gateway import llm_gateway

        assistant_message.metrics.start_timer()
        provider_response = await llm_gateway.acomplete(
            self._format_messages(messages, compress_tool_results),
            model=self.id,
            usage_type=self.gateway_usage_type,
            user_id=self.gateway_user_id,
            timeout_s=self.gateway_timeout_s,
            tools=tools,
            temperature=self.temperature,
            api_key=self.api_key,
        )
        assistant_message.metrics.stop_timer()

        return self._parse_provider_response(provider_response, response_format=response_format)


# ---------------------------------------------------------------------------
# Legacy Agent (kept for backward compatibility)
# ---------------------------------------------------------------------------


class Agent(BaseModel):
    """A configurable agent with tools, memory, and guardrails."""

    model_config = {"arbitrary_types_allowed": True}

    name: str
    role: str
    goal: str = ""
    system_prompt: str = ""
    llm: BaseLLM
    tools: list[BaseTool] = Field(default_factory=list)
    memory: Any = None
    guardrails: list[BaseGuardrail] = Field(default_factory=list)
    max_iterations: int = 10
    metadata: dict = Field(default_factory=dict)

    def get_system_message(self, memory_context: str = "") -> str:
        parts = []
        if self.system_prompt:
            parts.append(self.system_prompt)
        else:
            parts.append(f"You are {self.name}, a {self.role}.")
            if self.goal:
                parts.append(f"Your goal: {self.goal}")

        if memory_context:
            parts.append(f"\n## Relevant User Context\n{memory_context}")

        return "\n\n".join(parts)

    def get_tool_schemas(self) -> list[dict]:
        return [t.to_schema() for t in self.tools]

    def get_tool_by_name(self, name: str) -> BaseTool | None:
        for t in self.tools:
            if t.name == name:
                return t
        return None


# ---------------------------------------------------------------------------
# NaruResult
# ---------------------------------------------------------------------------


@dataclass
class HandoffRequest:
    """Request to hand off the conversation to another agent."""

    target: str  # delegate name (key in delegates map)
    message: str | None = None  # if set, overrides the original message
    reason: str = ""  # why the handoff occurred (for tracing)


@dataclass
class NaruResult:
    """Result returned by NaruAgent.chat()."""

    content: str = ""
    blocked: bool = False
    usage: dict = field(default_factory=dict)
    intent: IntentResult | None = None
    tool_calls: list[str] = field(default_factory=list)
    timings: dict = field(default_factory=dict)
    session_id: str | None = None
    trace_id: str | None = None
    trace: Trace | None = None
    handoff: HandoffRequest | None = None


@dataclass
class _RunPrep:
    """Internal carrier between _prepare_run and the agno-run / finalize steps.

    Lets the sync (chat) and async (achat) paths share one prefetch + finalize
    pipeline while differing only in how the main agno turn and the empty-content
    fallback are executed (thread-blocking vs await)."""

    blocked_result: NaruResult | None = None
    timings: dict[str, float] = field(default_factory=dict)
    t0: float = 0.0
    intent: IntentResult | None = None
    dynamic_instructions: list[str] = field(default_factory=list)
    skill_results: list = field(default_factory=list)
    user_id: str | None = None
    session_id: str | None = None
    fallback_text: str = ""


# ---------------------------------------------------------------------------
# NaruAgent — Agno-powered orchestrator
# ---------------------------------------------------------------------------


class NaruAgent:
    """High-level agent powered by Agno with built-in RAG, intent classification,
    memory, guardrails, tool-calling classification, session history, and tracing.

    Minimal usage::

        agent = NaruAgent(
            model="gemini/gemini-2.5-flash-lite",
            instructions=["You are a helpful assistant."],
        )
        result = agent.chat("Hello!")
        print(result.content)

    Full-featured usage::

        agent = NaruAgent(
            model="gemini/gemini-2.5-flash-lite",
            instructions=["You are a helpful assistant."],
            # Tools & RAG
            tools=[my_tool],
            knowledge_store=my_store,
            # Intent & tool calling classification
            intent_classifier=LLMIntentClassifier(),
            tool_calling_classifier=LLMToolCallingClassifier(),
            # Memory & guardrails
            memory=my_memory,
            guardrails=[my_guardrail],
            # Session history (auto-creates InMemoryDb if db is None)
            add_history_to_context=True,
            num_history_runs=3,
            # Tracing (auto-creates EventBus if not provided)
            trace_exporters=[JSONLTraceExporter("traces.jsonl")],
        )
        result = agent.chat("Hello!", user_id="user_123", session_id="s1")
        print(result.content)
    """

    def __init__(
        self,
        model: str = "gemini/gemini-2.5-flash-lite",
        api_key: str | None = None,
        name: str = "assistant",
        instructions: list[str] | None = None,
        # Tools — accepts naru_agent BaseTool or Agno Toolkit instances
        tools: list[Any] | None = None,
        # Tools always passed to the main LLM, unaffected by tool_calling_classifier
        always_tools: list[Any] | None = None,
        # RAG
        knowledge_store: BaseKnowledgeStore | None = None,
        knowledge_top_k: int = 3,
        knowledge_min_score: float = 0.3,
        # Intent
        intent_classifier: BaseIntentClassifier | None = None,
        tool_calling_classifier: BaseToolCallingClassifier | None = None,
        # Memory — MemoryManager or Mem0MemoryManager
        memory: Any | None = None,
        # Guardrails
        guardrails: list[BaseGuardrail] | None = None,
        # Agno options
        tool_call_limit: int = 10,
        max_parallel_tools: int | None = None,
        markdown: bool = False,
        temperature: float = 0.7,
        prefetch_timeout: float = 10.0,
        # Session management
        db: Any | None = None,
        add_history_to_context: bool = False,
        num_history_runs: int | None = None,
        num_history_messages: int | None = None,
        max_tool_calls_from_history: int | None = None,
        # Compression (Agno tool result compression)
        compress_tool_results: bool = False,
        compression_manager: Any | None = None,
        # Session summaries
        enable_session_summaries: bool = False,
        # Context compression (conversation history summarization)
        context_compression: bool = False,
        summary_store: Any | None = None,
        summary_model: str = "gemini/gemma-3-12b-it",
        summary_api_base: str | None = None,
        compression_keep_last_rounds: int = 5,
        compression_threshold_rounds: int = 5,
        # Extensions
        event_bus: Any | None = None,
        prefetch_hooks: list[Callable] | None = None,
        trace_exporters: list[Any] | None = None,
        usage_type: str = "rizo_chat",
        # Skills
        skills: list[Any] | None = None,
        skill_selector: Any | None = None,
        max_active_skills: int = 3,
    ) -> None:
        self.model_id = model
        self.api_key = api_key
        self.name = name
        self.instructions = instructions or []
        self.tools = tools or []
        self._naru_tools: list[BaseTool] = [t for t in self.tools if isinstance(t, BaseTool)]
        self._always_tools: list[Any] = always_tools or []
        self.knowledge_store = knowledge_store
        self.knowledge_top_k = knowledge_top_k
        self.knowledge_min_score = knowledge_min_score
        self.intent_classifier = intent_classifier
        self.tool_calling_classifier = tool_calling_classifier
        self.memory = memory
        self.guardrails = guardrails or []
        self.tool_call_limit = tool_call_limit
        self.max_parallel_tools = max_parallel_tools
        self.markdown = markdown
        self.temperature = temperature
        self.usage_type = usage_type
        self.prefetch_timeout = prefetch_timeout
        # Session management
        self.add_history_to_context = add_history_to_context
        self.num_history_runs = num_history_runs
        self.num_history_messages = num_history_messages
        self.max_tool_calls_from_history = max_tool_calls_from_history
        # Compression
        self.compress_tool_results = compress_tool_results
        self.compression_manager = compression_manager
        # Session summaries
        self.enable_session_summaries = enable_session_summaries
        # Context compression
        self._context_compressor = None
        if context_compression:
            from naru_agent.compression.compressor import ContextCompressor
            from naru_agent.compression.memory_store import InMemorySummaryStore
            store = summary_store or InMemorySummaryStore()
            self._context_compressor = ContextCompressor(
                summary_store=store,
                summary_model=summary_model,
                summary_api_base=summary_api_base,
                keep_last_rounds=compression_keep_last_rounds,
                threshold_rounds=compression_threshold_rounds,
            )
            # Auto-align num_history_runs with keep_last_rounds
            if num_history_runs is None:
                num_history_runs = compression_keep_last_rounds
                self.num_history_runs = num_history_runs
            # Ensure history is enabled
            if not add_history_to_context:
                logger.warning(
                    "context_compression=True requires add_history_to_context; "
                    "forcing add_history_to_context=True"
                )
                add_history_to_context = True
        # Auto-create InMemoryDb when history is enabled but no db given
        if add_history_to_context and db is None:
            from agno.db.in_memory import InMemoryDb
            self.db = InMemoryDb()
        else:
            self.db = db
        # Extensions
        self._trace_exporters = trace_exporters or []
        # Auto-create EventBus if trace_exporters provided without one
        if self._trace_exporters and event_bus is None:
            from naru_agent.events import EventBus
            event_bus = EventBus()
        self.event_bus = event_bus
        self.prefetch_hooks = prefetch_hooks or []
        # Skills
        self._skill_registry = None
        if skills:
            from naru_agent.skills import SkillRegistry, KeywordSkillSelector
            selector = skill_selector or KeywordSkillSelector()
            self._skill_registry = SkillRegistry(skills, selector, max_active_skills)
        # TraceCollector — wired only when both event_bus and trace_exporters exist
        self._trace_collector: Any | None = None
        if self.event_bus and self._trace_exporters:
            from naru_agent.tracing.collector import TraceCollector
            self._trace_collector = TraceCollector(self.event_bus)
        # Cache the Agno LiteLLM model instance (stateless, safe to reuse)
        self._agno_model = None
        self._model_lock = threading.Lock()
        # Dedicated executor for parallel prefetch (intent, memory, RAG, hooks)
        self._prefetch_executor = ThreadPoolExecutor(max_workers=4)
        # Shared executor for background tasks (memory save, etc.)
        self._bg_executor = ThreadPoolExecutor(max_workers=2)
        # Cached AgnoAgent — recreated only on first call; instructions/tools
        # are updated before each run. All persistent session state is stored
        # in self.db (Agno DB) via session_id, so reusing the agent object is
        # safe. The Paceriz path serializes same-session turns one layer up via a
        # per-session asyncio.Lock; the old cross-thread _agno_run_lock was removed
        # with the move to a single-event-loop async path (achat).
        self._agno_agent: AgnoAgent | None = None
        # weakref.finalize runs on GC (short-lived agents) or process exit
        # (long-lived agents), avoiding atexit handler accumulation.
        weakref.finalize(
            self,
            NaruAgent._shutdown_static,
            self._prefetch_executor,
            self._bg_executor,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(
        self,
        message: str,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> NaruResult:
        """Send a message and get a response (synchronous).

        Orchestration flow:
        1. Input guardrails
        2. Parallel prefetch (memory, intent, RAG, custom hooks)
        3. Build instructions based on intent
        4. Run Agno Agent
        5. Output guardrails
        6. Background memory save

        Kept for naru's own tests and any synchronous consumer. The Paceriz
        request path uses achat() (single-event-loop, non-blocking).
        """
        prep = self._prepare_run(message, user_id, session_id)
        if prep.blocked_result is not None:
            return prep.blocked_result
        agno_result = self._run_agno_sync(message, prep)
        return self._finalize_run(message, user_id, session_id, prep, agno_result)

    async def achat(
        self,
        message: str,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> NaruResult:
        """Async twin of chat(): same prefetch/instruction-building, but the main
        agno turn runs via Agent.arun (real async I/O — yields the event loop while
        the upstream LLM is in flight) and the empty-content fallback goes through
        the shared async LLM gateway. Single authoritative pipeline shared with
        chat() via _prepare_run / _finalize_run (no logic duplicated)."""
        prep = await asyncio.to_thread(self._prepare_run, message, user_id, session_id)
        if prep.blocked_result is not None:
            return prep.blocked_result
        agno_result = await self._run_agno_async(message, prep)
        return self._finalize_run(message, user_id, session_id, prep, agno_result)

    # ------------------------------------------------------------------
    # Shared run pipeline (sync chat + async achat both use these)
    # ------------------------------------------------------------------

    def _prepare_run(
        self,
        message: str,
        user_id: str | None,
        session_id: str | None,
    ) -> "_RunPrep":
        """Phases 1-3: guardrails + parallel prefetch + instruction building.

        Identical for sync and async paths. Returns a _RunPrep carrying everything
        the agno run + finalize steps need. If an input guardrail blocks the turn,
        _RunPrep.blocked_result is set (trace already exported) and the caller
        returns it directly."""
        timings: dict[str, float] = {}
        t0 = time.perf_counter()

        # Start trace
        if self._trace_collector:
            self._trace_collector.start_trace(message, user_id, session_id)

        # 1. Input guardrails
        for guard in self.guardrails:
            result = guard.check_input(message)
            if not result.passed:
                blocked_result = NaruResult(
                    content=result.modified_text or "Request blocked.",
                    blocked=True,
                    session_id=session_id,
                )
                self._finish_and_export_trace(blocked_result)
                return _RunPrep(blocked_result=blocked_result)

        # 2. Parallel prefetch (two phases if intent classifier exists)
        t_prefetch = time.perf_counter()
        memory_context = ""
        intent = IntentResult(needs_knowledge=True, needs_tools=True, raw="")
        knowledge_text = ""
        hook_results: list[str] = []

        # Phase A: intent + memory + summary + custom hooks in parallel
        summary_text = ""
        futures_map: dict[str, Any] = {}
        pool = self._prefetch_executor
        if self.memory and user_id:
            futures_map["memory"] = pool.submit(
                self._fetch_memory, user_id, message
            )
        if self.intent_classifier:
            futures_map["intent"] = pool.submit(
                self.intent_classifier.classify, message
            )
        if self._context_compressor and session_id:
            futures_map["summary"] = pool.submit(
                self._context_compressor.get_summary_sync, session_id
            )
        for i, hook in enumerate(self.prefetch_hooks):
            futures_map[f"hook_{i}"] = pool.submit(hook, message, user_id)

        # If no intent classifier, also fetch RAG in parallel (always needed)
        if self.knowledge_store and not self.intent_classifier:
            futures_map["knowledge"] = pool.submit(
                self._fetch_knowledge, message
            )

        prefetch_timings: dict[str, float] = {}
        for key, future in futures_map.items():
            t_key = time.perf_counter()
            try:
                val = future.result(timeout=self.prefetch_timeout)
            except FuturesTimeoutError:
                # Sentinel: a timed-out prefetch silently drops its context (e.g. the
                # verdict/HR block), leaving the LLM ungrounded -> it may fabricate.
                # Structured so Cloud Logging can build a metric on
                # jsonPayload.event_type="prefetch_timeout". Expected ~0 in healthy prod
                # (context build is sub-second co-located); non-zero => GCP latency/outage.
                logger.warning({
                    "event_type": "prefetch_timeout",
                    "prefetch_hook": key,
                    "timeout_s": self.prefetch_timeout,
                    "message": (f"Prefetch '{key}' timed out after {self.prefetch_timeout}s; "
                                "context not injected (LLM ungrounded)"),
                })
                val = "" if key != "intent" else IntentResult(
                    needs_knowledge=True, needs_tools=True, raw=""
                )
            except Exception:
                logger.warning({
                    "event_type": "prefetch_failed",
                    "prefetch_hook": key,
                    "message": f"Prefetch '{key}' failed",
                }, exc_info=True)
                val = "" if key != "intent" else IntentResult(
                    needs_knowledge=True, needs_tools=True, raw=""
                )
            prefetch_timings[key] = (time.perf_counter() - t_key) * 1000

            if key == "memory":
                memory_context = val or ""
            elif key == "intent":
                intent = val
            elif key == "knowledge":
                knowledge_text = val or ""
            elif key == "summary":
                if val:
                    summary_text = val.summary_text
            elif key.startswith("hook_"):
                if val:
                    hook_results.append(str(val))

        # Emit memory/intent/knowledge events for tracing
        if self.event_bus:
            if "memory" in prefetch_timings:
                self.event_bus.emit("memory_retrieved", {
                    "user_id": user_id,
                    "query": message,
                    "items_count": memory_context.count("\n") + 1 if memory_context else 0,
                    "latency_ms": prefetch_timings.get("memory"),
                })
            if "intent" in prefetch_timings:
                self.event_bus.emit("intent_classified", {
                    "result": intent,
                    "latency_ms": prefetch_timings.get("intent"),
                })
            if "knowledge" in prefetch_timings:
                self.event_bus.emit("knowledge_retrieved", {
                    "query": message,
                    "chunks_count": knowledge_text.count("\n") + 1 if knowledge_text else 0,
                    "latency_ms": prefetch_timings.get("knowledge"),
                })

        # Phase B: fetch RAG only if intent says knowledge is needed
        if (
            self.knowledge_store
            and self.intent_classifier
            and intent.needs_knowledge
        ):
            t_rag = time.perf_counter()
            knowledge_text = self._fetch_knowledge(message)
            if self.event_bus:
                self.event_bus.emit("knowledge_retrieved", {
                    "query": message,
                    "chunks_count": knowledge_text.count("\n") + 1 if knowledge_text else 0,
                    "latency_ms": (time.perf_counter() - t_rag) * 1000,
                })

        timings["prefetch"] = time.perf_counter() - t_prefetch

        # === Skill execution ===
        skill_results: list = []
        if self._skill_registry:
            try:
                from naru_agent.skills.base import SkillContext
                skill_context = SkillContext(
                    message=message,
                    user_id=user_id,
                    session_id=session_id,
                    memory_context=memory_context,
                    knowledge_store=self.knowledge_store,
                )
                skill_results = self._skill_registry.run_skills(message, skill_context)
            except Exception:
                logger.warning("Skill execution failed", exc_info=True)

        # Phase C: Tool calling classification
        tool_calling_result = None
        if self.tool_calling_classifier and intent.needs_tools and self._naru_tools:
            t_tc = time.perf_counter()
            try:
                tool_calling_result = self.tool_calling_classifier.classify(
                    message, self._naru_tools
                )
            except Exception:
                logger.warning("Tool calling classifier failed", exc_info=True)
            tc_latency = (time.perf_counter() - t_tc) * 1000
            if self.event_bus and tool_calling_result:
                self.event_bus.emit("tool_calling_classified", {
                    "tools_called": [r["tool"] for r in tool_calling_result.tool_results],
                    "usage": tool_calling_result.usage,
                    "latency_ms": tc_latency,
                })

        # 3. Build instructions
        dynamic_instructions = list(self.instructions)

        if summary_text:
            dynamic_instructions.append(
                f"\n【Conversation History Summary】\n{summary_text}"
            )

        if intent.needs_knowledge and knowledge_text:
            dynamic_instructions.append(f"\n【Knowledge】\n{knowledge_text}")

        if memory_context:
            dynamic_instructions.append(f"\n【Memory】\n{memory_context}")

        for hr in hook_results:
            dynamic_instructions.append(hr)

        # === Skill prompt injection ===
        _system_overridden = False
        for sr in skill_results:
            if sr.skipped or not sr.prompt_injection:
                continue
            if sr.override_system_prompt is not None:
                if _system_overridden:
                    logger.warning("Multiple skills override system prompt; ignoring %s", sr.skill_name)
                    continue
                _system_overridden = True
                if dynamic_instructions:
                    dynamic_instructions[0] = sr.override_system_prompt
                else:
                    dynamic_instructions.insert(0, sr.override_system_prompt)
            else:
                dynamic_instructions.append(sr.prompt_injection)

        # Inject tool results from classifier into instructions
        if tool_calling_result and tool_calling_result.tool_results:
            results_text = "\n".join(
                f"[{r['tool']}] {r['result']}" for r in tool_calling_result.tool_results
            )
            dynamic_instructions.append(f"\n【Tool Results】\n{results_text}")
            # Override intent so main agent doesn't carry tool schemas
            intent = IntentResult(
                needs_knowledge=intent.needs_knowledge,
                needs_tools=False,
                raw=intent.raw,
            )

        return _RunPrep(
            timings=timings,
            t0=t0,
            intent=intent,
            dynamic_instructions=dynamic_instructions,
            skill_results=skill_results,
            user_id=user_id,
            session_id=session_id,
        )

    def _ensure_agno_agent(self, dynamic_instructions: list[str], intent, skill_results) -> None:
        """Lazily build (once) and mutate the cached AgnoAgent for this turn.

        Instructions/tools are per-turn; persistent session state lives in self.db
        keyed by session_id, so reusing the agent object is safe."""
        skill_extra_tools = [t for sr in skill_results for t in sr.extra_tools]
        agno_tools = self._prepare_tools(intent.needs_tools, extra_tools=skill_extra_tools or None)
        if self._agno_agent is None:
            static_kwargs: dict[str, Any] = {
                "model": self._get_agno_model(),
                "markdown": self.markdown,
                "tool_call_limit": self.tool_call_limit,
            }
            if self.db is not None:
                static_kwargs["db"] = self.db
                static_kwargs["add_history_to_context"] = self.add_history_to_context
                if self.num_history_runs is not None:
                    static_kwargs["num_history_runs"] = self.num_history_runs
                if self.num_history_messages is not None:
                    static_kwargs["num_history_messages"] = self.num_history_messages
                if self.max_tool_calls_from_history is not None:
                    static_kwargs["max_tool_calls_from_history"] = self.max_tool_calls_from_history
            if self.compress_tool_results:
                static_kwargs["compress_tool_results"] = True
                if self.compression_manager is not None:
                    static_kwargs["compression_manager"] = self.compression_manager
            if self.enable_session_summaries:
                static_kwargs["enable_session_summaries"] = True
            self._agno_agent = AgnoAgent(**static_kwargs)

        self._agno_agent.instructions = dynamic_instructions
        self._agno_agent.tools = agno_tools if agno_tools else None

    @staticmethod
    def _run_kwargs(user_id: str | None, session_id: str | None) -> dict[str, Any]:
        run_kwargs: dict[str, Any] = {}
        if user_id is not None:
            run_kwargs["user_id"] = user_id
        if session_id is not None:
            run_kwargs["session_id"] = session_id
        return run_kwargs

    def _emit_after_llm(self, agno_result, llm_latency_ms: float) -> None:
        if not self.event_bus:
            return
        self.event_bus.emit("after_llm_call", {
            "iteration": 0,
            "model": self.model_id,
            "has_tool_calls": bool(agno_result.messages and any(
                hasattr(m, "tool_calls") and m.tool_calls
                for m in agno_result.messages
            )),
            "response_content": agno_result.content or "",
            "tool_calls": [],
            "usage": {},
            "latency_ms": llm_latency_ms,
        })

    def _run_agno_sync(self, message: str, prep: "_RunPrep"):
        """Synchronous agno turn (naru's own tests / synchronous consumers).

        The previous cross-thread _agno_run_lock is gone: the Paceriz request path
        no longer calls this (it uses achat on a single event loop, serialized
        per-session by an asyncio.Lock), and the remaining synchronous callers are
        naru's single-threaded tests. Callers needing concurrent sync use on one
        NaruAgent must serialize externally."""
        t_agent = time.perf_counter()
        run_kwargs = self._run_kwargs(prep.user_id, prep.session_id)
        self._ensure_agno_agent(prep.dynamic_instructions, prep.intent, prep.skill_results)
        if self.event_bus:
            self.event_bus.emit("before_llm_call", {
                "iteration": 0,
                "message_count": len(prep.dynamic_instructions) + 1,
            })
        t_llm = time.perf_counter()
        agno_result = self._agno_agent.run(message, **run_kwargs)
        llm_latency_ms = (time.perf_counter() - t_llm) * 1000
        self._emit_after_llm(agno_result, llm_latency_ms)
        prep.timings["agent_run"] = time.perf_counter() - t_agent
        prep.fallback_text = self._empty_content_fallback_sync(agno_result, prep.dynamic_instructions)
        return agno_result

    async def _run_agno_async(self, message: str, prep: "_RunPrep"):
        """Async agno turn via Agent.arun — yields the event loop while the upstream
        LLM is in flight. No threading lock: under uvicorn --workers 1 the event loop
        is single-threaded, and same-session serialization is enforced one layer up
        by the per-session asyncio.Lock (orchestrator_service.chat). Concurrent achat()
        across *different* sessions on one NaruAgent instance is not a Paceriz pattern
        (each request builds fresh per-uid delegates), so agent-object mutation races
        are not introduced here."""
        t_agent = time.perf_counter()
        run_kwargs = self._run_kwargs(prep.user_id, prep.session_id)
        self._ensure_agno_agent(prep.dynamic_instructions, prep.intent, prep.skill_results)
        if self.event_bus:
            self.event_bus.emit("before_llm_call", {
                "iteration": 0,
                "message_count": len(prep.dynamic_instructions) + 1,
            })
        t_llm = time.perf_counter()
        if isinstance(self._agno_model, _GatewayLiteLLM):
            self._agno_model.gateway_user_id = prep.user_id or ""
        agno_result = await self._agno_agent.arun(message, **run_kwargs)
        llm_latency_ms = (time.perf_counter() - t_llm) * 1000
        self._emit_after_llm(agno_result, llm_latency_ms)
        prep.timings["agent_run"] = time.perf_counter() - t_agent
        prep.fallback_text = await self._empty_content_fallback_async(agno_result, prep.dynamic_instructions)
        return agno_result

    def _needs_empty_content_fallback(self, agno_result) -> bool:
        if agno_result.content or not agno_result.messages:
            return False
        return any(
            getattr(m, "role", "") == "tool" and getattr(m, "content", "")
            for m in agno_result.messages
        )

    def _build_fallback_messages(self, agno_result, dynamic_instructions) -> list[dict[str, Any]]:
        """Reconstruct the full multi-turn context so the fallback model sees the
        structured tool call / result history instead of a flattened text blob.
        Append an explicit answer-now directive: without it, flash-lite sometimes
        parrots the user's question back instead of synthesising the tool results +
        injected context into an answer (observed on data_query when tools returned
        "no data")."""
        return [
            {"role": "system", "content": "\n\n".join(dynamic_instructions)},
        ] + self._agno_messages_to_litellm(agno_result.messages) + [
            {"role": "user", "content": _FALLBACK_ANSWER_DIRECTIVE},
        ]

    def _empty_content_fallback_sync(self, agno_result, dynamic_instructions) -> str:
        """Sync empty-content fallback (legacy litellm.completion path). Returns ""
        when no fallback is needed or it fails — _finalize_run then applies the safe
        default reply."""
        if not self._needs_empty_content_fallback(agno_result):
            return ""
        logger.info("Empty content after tool calls, falling back")
        try:
            import litellm
            kwargs: dict[str, Any] = {
                "model": self.model_id,
                "messages": self._build_fallback_messages(agno_result, dynamic_instructions),
                "temperature": self.temperature,
            }
            if self.api_key:
                kwargs["api_key"] = self.api_key
            fallback_resp = litellm.completion(**kwargs)
            if not fallback_resp.choices:
                raise ValueError("Fallback LLM also returned empty choices")
            return fallback_resp.choices[0].message.content or ""
        except Exception:
            logger.warning("Fallback completion also failed")
            return ""

    async def _empty_content_fallback_async(self, agno_result, dynamic_instructions) -> str:
        """Async empty-content fallback via the shared LLM gateway (non-blocking,
        concurrency-capped). Mirrors _empty_content_fallback_sync."""
        if not self._needs_empty_content_fallback(agno_result):
            return ""
        logger.info("Empty content after tool calls, falling back (async gateway)")
        try:
            from naru_agent.llm.async_gateway import llm_gateway
            resp = await llm_gateway.acomplete(
                self._build_fallback_messages(agno_result, dynamic_instructions),
                model=self.model_id,
                usage_type="empty_content_fallback",
                user_id="",
                timeout_s=30,
                temperature=self.temperature,
                api_key=self.api_key,
            )
            return resp.choices[0].message.content or ""
        except Exception:
            logger.warning("Async fallback completion also failed", exc_info=True)
            return ""

    def _finalize_run(
        self,
        message: str,
        user_id: str | None,
        session_id: str | None,
        prep: "_RunPrep",
        agno_result,
    ) -> NaruResult:
        """Phases after the agno turn: tool-call/usage extraction, empty-content
        fallback (sync litellm — kept in scope per the async-loop task; a follow-up
        moves it onto the gateway), output guardrails, background memory/compression,
        trace export. Shared by chat() and achat()."""
        timings = prep.timings
        intent = prep.intent
        dynamic_instructions = prep.dynamic_instructions
        t0 = prep.t0

        # Extract tool calls
        tool_calls_made: list[str] = []
        if agno_result.messages:
            for msg in agno_result.messages:
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        if isinstance(tc, dict):
                            fn = tc.get("function", {})
                            name = fn.get("name", "?") if isinstance(fn, dict) else str(fn)
                        else:
                            name = getattr(
                                getattr(tc, "function", None), "name", str(tc)
                            )
                        tool_calls_made.append(name)

        # Extract usage
        usage_info: dict[str, Any] = {}
        if agno_result.metrics:
            m = agno_result.metrics
            total_in = m.input_tokens or 0
            total_out = m.output_tokens or 0
            usage_info = {
                "input": total_in,
                "output": total_out,
                "total": total_in + total_out,
            }

        # Fallback: tool calls succeeded but content empty. The actual LLM fallback
        # ran in the run-specific method (_run_agno_sync uses litellm.completion;
        # _run_agno_async uses the async gateway) and its result is on prep.fallback_text.
        response_text = agno_result.content or prep.fallback_text or ""

        if not response_text:
            response_text = "抱歉，我剛剛出了一點狀況，可以再說一次嗎？"

        # 6. Output guardrails
        for guard in self.guardrails:
            result = guard.check_output(response_text)
            if not result.passed:
                response_text = result.modified_text or response_text

        # 7. Background memory save
        if (
            self.memory
            and user_id
            and len(message) + len(response_text) > 100
        ):
            latest_turn = [
                {"role": "user", "content": message},
                {"role": "assistant", "content": response_text},
            ]
            self._bg_executor.submit(self._save_memory_safe, user_id, latest_turn)

        # 8. Background context compression
        if self._context_compressor and session_id and self._agno_agent:
            agent_ref = self._agno_agent
            self._bg_executor.submit(
                self._context_compressor.maybe_compress, session_id, agent_ref,
            )

        timings["total"] = time.perf_counter() - t0

        if self.event_bus:
            self.event_bus.emit("chat_complete", {
                "timings": timings,
                "tool_calls": tool_calls_made,
                "intent": intent,
            })

        final_result = NaruResult(
            content=response_text,
            usage=usage_info,
            intent=intent,
            tool_calls=tool_calls_made,
            timings=timings,
            session_id=session_id,
        )

        self._finish_and_export_trace(final_result)

        return final_result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _finish_and_export_trace(self, result: NaruResult) -> None:
        """End the current trace, attach it to the result, and export."""
        if not self._trace_collector:
            return
        trace = self._trace_collector.end_trace(result)
        result.trace_id = trace.trace_id
        result.trace = trace
        for exporter in self._trace_exporters:
            self._bg_executor.submit(exporter.export, trace)

    def _get_agno_model(self):
        """Return cached Agno LiteLLM model instance (thread-safe)."""
        with self._model_lock:
            if self._agno_model is None:
                model_kwargs: dict[str, Any] = {"id": self.model_id, "temperature": self.temperature}
                if self.api_key:
                    model_kwargs["api_key"] = self.api_key
                self._agno_model = _GatewayLiteLLM(**model_kwargs)
                self._agno_model.gateway_usage_type = self.usage_type
            return self._agno_model

    def _fetch_memory(self, user_id: str, message: str) -> str:
        try:
            return self.memory.get_context_string(user_id, message) or ""
        except Exception:
            logger.warning("Failed to get memory context for user_id=%s", user_id)
            return ""

    def _fetch_knowledge(self, message: str) -> str:
        try:
            results = self.knowledge_store.search(message, top_k=self.knowledge_top_k)
            return self.knowledge_store.format_context(
                results, min_score=self.knowledge_min_score
            )
        except Exception:
            logger.warning("Knowledge fetch failed")
            return ""

    def _prepare_tools(self, needs_tools: bool, extra_tools: list[BaseTool] | None = None) -> list[Any]:
        """Convert tools to Agno-compatible format.

        always_tools are always appended regardless of needs_tools,
        allowing write-side tools to bypass the tool_calling_classifier.

        If max_parallel_tools is set, a shared threading.Semaphore is created
        and passed to all NaruToolkit instances so that at most that many tool
        calls run concurrently within a single agent turn.
        """
        import threading

        from naru_agent.tools.agno_adapter import NaruToolkit

        semaphore = (
            threading.Semaphore(self.max_parallel_tools)
            if self.max_parallel_tools
            else None
        )

        agno_tools: list[Any] = []

        if needs_tools and self.tools:
            naru_tools: list[BaseTool] = []
            for t in self.tools:
                if isinstance(t, BaseTool):
                    naru_tools.append(t)
                else:
                    agno_tools.append(t)
            if naru_tools:
                agno_tools.append(NaruToolkit(naru_tools, semaphore=semaphore).toolkit)

        if extra_tools:
            agno_tools.append(NaruToolkit(extra_tools, semaphore=semaphore).toolkit)

        if self._always_tools:
            always_naru: list[BaseTool] = []
            for t in self._always_tools:
                if isinstance(t, BaseTool):
                    always_naru.append(t)
                else:
                    agno_tools.append(t)
            if always_naru:
                agno_tools.append(NaruToolkit(always_naru, semaphore=semaphore).toolkit)

        return agno_tools

    def _save_memory_safe(self, user_id: str, messages: list[dict]) -> None:
        try:
            self.memory.add(user_id, messages)
        except Exception:
            logger.exception("Background memory save failed for user_id=%s", user_id)

    @staticmethod
    def _agno_messages_to_litellm(messages: list[Any]) -> list[dict[str, Any]]:
        """Convert Agno message objects to litellm-compatible message dicts."""
        result: list[dict[str, Any]] = []
        for msg in messages:
            role = getattr(msg, "role", None)
            if role not in ("user", "assistant", "tool"):
                continue
            content = getattr(msg, "content", None) or ""
            d: dict[str, Any] = {"role": role, "content": content}
            if role == "assistant":
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls:
                    d["tool_calls"] = tool_calls
            elif role == "tool":
                tool_call_id = getattr(msg, "tool_call_id", None)
                if tool_call_id:
                    d["tool_call_id"] = tool_call_id
                name = getattr(msg, "name", None)
                if name:
                    d["name"] = name
            result.append(d)
        return result

    @staticmethod
    def _shutdown_static(
        prefetch_exec: ThreadPoolExecutor,
        bg_exec: ThreadPoolExecutor,
    ) -> None:
        """Executor cleanup — called by weakref.finalize on GC or process exit."""
        prefetch_exec.shutdown(wait=False, cancel_futures=True)
        bg_exec.shutdown(wait=True, cancel_futures=False)
