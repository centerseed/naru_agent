"""Adapter to convert naru_agent BaseTool instances into an Agno Toolkit."""

from __future__ import annotations

import inspect
import logging
from typing import Any

from naru_agent.tools.base import BaseTool

logger = logging.getLogger(__name__)


def _build_wrapper(naru_tool: BaseTool):
    """Build a plain function that wraps a BaseTool.run() call.

    The wrapper has the correct signature and docstring so that
    Agno can register it as a tool.
    """
    schema = naru_tool.args_schema
    if schema is None:
        # No args — simple wrapper
        def wrapper() -> str:
            return naru_tool.run()

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
        return naru_tool.run(**kwargs)

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
    """

    def __init__(self, tools: list[BaseTool]) -> None:
        from agno.tools.toolkit import Toolkit

        self._toolkit = Toolkit(name="naru_tools")
        for t in tools:
            try:
                fn = _build_wrapper(t)
                self._toolkit.register(fn)
            except Exception:
                logger.exception("Failed to register tool '%s'", t.name)

    @property
    def toolkit(self):
        """Return the underlying Agno Toolkit instance."""
        return self._toolkit
