"""Adapter to convert naru_agent BaseTool instances into an Agno Toolkit."""

from __future__ import annotations

import inspect
import logging
import threading
from typing import Any

from naru_agent.tools.base import BaseTool

logger = logging.getLogger(__name__)


def _build_wrapper(
    naru_tool: BaseTool,
    semaphore: threading.Semaphore | None = None,
    call_cache: dict[str, str] | None = None,
):
    """Build a plain function that wraps a BaseTool.run() call.

    The wrapper has the correct signature and docstring so that
    Agno can register it as a tool.

    If *semaphore* is provided, each tool call acquires it before executing
    and releases it afterward, limiting parallel tool execution.

    If *call_cache* is provided, identical calls (same tool + same args) within
    the same turn are deduplicated — the cached result is returned immediately
    without re-executing the tool.  Pass a fresh ``{}`` per turn to scope the
    cache to a single ReAct loop iteration (TOOL_STORM prevention).
    """
    schema = naru_tool.args_schema
    if schema is None:
        # No args — simple wrapper
        def wrapper() -> str:
            cache_key = naru_tool.name
            if call_cache is not None and cache_key in call_cache:
                logger.debug("tool_dedup hit: %s", cache_key)
                return call_cache[cache_key]
            if semaphore:
                semaphore.acquire()
            try:
                result = naru_tool.run()
            finally:
                if semaphore:
                    semaphore.release()
            if call_cache is not None:
                call_cache[cache_key] = result
            return result

        wrapper.__name__ = naru_tool.name
        wrapper.__doc__ = naru_tool.description
        return wrapper

    # Build parameter list from the Pydantic model
    fields = schema.model_fields
    params: list[inspect.Parameter] = []
    for field_name, field_info in fields.items():
        default = (
            inspect.Parameter.empty
            if field_info.is_required()
            else field_info.default
        )
        params.append(
            inspect.Parameter(
                name=field_name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=field_info.annotation,
            )
        )

    def wrapper(**kwargs: Any) -> str:
        cache_key = f"{naru_tool.name}:{sorted(kwargs.items())}"
        if call_cache is not None and cache_key in call_cache:
            logger.debug("tool_dedup hit: %s", cache_key)
            return call_cache[cache_key]
        if semaphore:
            semaphore.acquire()
        try:
            result = naru_tool.run(**kwargs)
        finally:
            if semaphore:
                semaphore.release()
        if call_cache is not None:
            call_cache[cache_key] = result
        return result

    wrapper.__name__ = naru_tool.name
    wrapper.__doc__ = naru_tool.description
    wrapper.__signature__ = inspect.Signature(params)  # type: ignore[attr-defined]

    # Set type hints for Agno introspection
    annotations = {f: info.annotation for f, info in fields.items()}
    annotations["return"] = str
    wrapper.__annotations__ = annotations

    return wrapper


class NaruToolkit:
    """Wraps a list of naru_agent BaseTool instances into an Agno-compatible Toolkit.

    Usage::

        from agno.agent import Agent
        toolkit = NaruToolkit(naru_tools)
        agent = Agent(tools=[toolkit], ...)

    Pass *semaphore* to limit how many tools execute in parallel::

        sem = threading.Semaphore(2)
        toolkit = NaruToolkit(naru_tools, semaphore=sem)

    Set ``deduplicate_calls=False`` to disable per-turn deduplication (e.g. for
    side-effectful tools that intentionally repeat the same call).
    """

    def __init__(
        self,
        tools: list[BaseTool],
        semaphore: threading.Semaphore | None = None,
        deduplicate_calls: bool = True,
    ) -> None:
        from agno.tools.function import Function
        from agno.tools.toolkit import Toolkit

        self._toolkit = Toolkit(name="naru_tools")
        # Shared cache for this toolkit instance — scoped to one turn because
        # NaruToolkit is created fresh per turn in AgnoAgent.
        call_cache: dict[str, str] | None = {} if deduplicate_calls else None
        for t in tools:
            try:
                fn = _build_wrapper(t, semaphore=semaphore, call_cache=call_cache)
                # Toolkit.register(callable) constructs Function directly in
                # Agno 2.5.x and therefore skips callable introspection.  Use
                # Naru's Pydantic schema as the source of truth so enum/range/
                # default constraints survive the adapter unchanged.
                parameters = t.to_schema()["function"]["parameters"]
                self._toolkit.register(Function(
                    name=t.name,
                    description=t.description,
                    parameters=parameters,
                    entrypoint=fn,
                    skip_entrypoint_processing=True,
                ))
            except Exception:
                logger.exception("Failed to register tool '%s'", t.name)

    @property
    def toolkit(self):
        """Return the underlying Agno Toolkit instance."""
        return self._toolkit
