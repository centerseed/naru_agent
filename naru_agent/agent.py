from __future__ import annotations

import logging
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
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
        summary_model: str = "ollama/gemma:12b",
        summary_api_base: str | None = None,
        compression_keep_last_rounds: int = 5,
        compression_threshold_rounds: int = 5,
        # Extensions
        event_bus: Any | None = None,
        prefetch_hooks: list[Callable] | None = None,
        trace_exporters: list[Any] | None = None,
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
        self.markdown = markdown
        self.temperature = temperature
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
        # safe. Concurrent chat() calls on the same NaruAgent are serialized
        # by _agno_run_lock (LLM latency dwarfs lock overhead).
        self._agno_agent: AgnoAgent | None = None
        self._agno_run_lock = threading.Lock()
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
        """Send a message and get a response.

        Orchestration flow:
        1. Input guardrails
        2. Parallel prefetch (memory, intent, RAG, custom hooks)
        3. Build instructions based on intent
        4. Run Agno Agent
        5. Output guardrails
        6. Background memory save
        """
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
                return blocked_result

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
            except Exception:
                logger.warning("Prefetch '%s' failed", key)
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

        # 5. Run Agno Agent
        t_agent = time.perf_counter()

        run_kwargs: dict[str, Any] = {}
        if user_id is not None:
            run_kwargs["user_id"] = user_id
        if session_id is not None:
            run_kwargs["session_id"] = session_id

        with self._agno_run_lock:
            # 4. Prepare tools (inside lock — keeps tool preparation and agent
            # mutation atomic, preventing fragile split if _prepare_tools evolves)
            agno_tools = self._prepare_tools(intent.needs_tools)
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

            if self.event_bus:
                self.event_bus.emit("before_llm_call", {
                    "iteration": 0,
                    "message_count": len(dynamic_instructions) + 1,
                })

            t_llm = time.perf_counter()
            agno_result = self._agno_agent.run(message, **run_kwargs)
            llm_latency_ms = (time.perf_counter() - t_llm) * 1000

            if self.event_bus:
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

        timings["agent_run"] = time.perf_counter() - t_agent

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

        # Fallback: tool calls succeeded but content empty
        response_text = agno_result.content or ""
        if not response_text and agno_result.messages:
            tool_results = [
                getattr(m, "content", "")
                for m in agno_result.messages
                if getattr(m, "role", "") == "tool" and getattr(m, "content", "")
            ]
            if tool_results:
                logger.info("Empty content after tool calls, falling back")
                try:
                    import litellm

                    # Reconstruct the full multi-turn context so the fallback
                    # model sees the structured tool call / result history
                    # instead of a flattened text blob.
                    fallback_messages: list[dict[str, Any]] = [
                        {"role": "system", "content": "\n\n".join(dynamic_instructions)},
                    ] + self._agno_messages_to_litellm(agno_result.messages)
                    kwargs: dict[str, Any] = {
                        "model": self.model_id,
                        "messages": fallback_messages,
                        "temperature": self.temperature,
                    }
                    if self.api_key:
                        kwargs["api_key"] = self.api_key
                    fallback_resp = litellm.completion(**kwargs)
                    response_text = fallback_resp.choices[0].message.content or ""
                except Exception:
                    logger.warning("Fallback completion also failed")

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
                model_kwargs: dict[str, Any] = {"id": self.model_id}
                if self.api_key:
                    model_kwargs["api_key"] = self.api_key
                self._agno_model = AgnoLiteLLM(**model_kwargs)
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

    def _prepare_tools(self, needs_tools: bool) -> list[Any]:
        """Convert tools to Agno-compatible format.

        always_tools are always appended regardless of needs_tools,
        allowing write-side tools to bypass the tool_calling_classifier.
        """
        from naru_agent.tools.agno_adapter import NaruToolkit

        agno_tools: list[Any] = []

        if needs_tools and self.tools:
            naru_tools: list[BaseTool] = []
            for t in self.tools:
                if isinstance(t, BaseTool):
                    naru_tools.append(t)
                else:
                    agno_tools.append(t)
            if naru_tools:
                agno_tools.append(NaruToolkit(naru_tools).toolkit)

        if self._always_tools:
            always_naru: list[BaseTool] = []
            for t in self._always_tools:
                if isinstance(t, BaseTool):
                    always_naru.append(t)
                else:
                    agno_tools.append(t)
            if always_naru:
                agno_tools.append(NaruToolkit(always_naru).toolkit)

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
