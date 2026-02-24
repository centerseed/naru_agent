from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from typing import Any, Callable, get_type_hints

from pydantic import BaseModel, Field, create_model


class BaseTool(ABC):
    """Base class for all tools. Subclass or use the @tool decorator."""

    name: str
    description: str
    args_schema: type[BaseModel] | None = None

    @abstractmethod
    def run(self, **kwargs: Any) -> str:
        ...

    def to_schema(self) -> dict:
        """Convert to OpenAI-compatible function calling schema."""
        properties = {}
        required = []

        if self.args_schema:
            schema = self.args_schema.model_json_schema()
            properties = schema.get("properties", {})
            required = schema.get("required", [])

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


class FunctionTool(BaseTool):
    """A tool created from a plain function."""

    def __init__(
        self,
        func: Callable,
        name: str | None = None,
        description: str | None = None,
        args_schema: type[BaseModel] | None = None,
    ):
        self._func = func
        self.name = name or func.__name__
        self.description = description or func.__doc__ or ""
        self.args_schema = args_schema or _schema_from_function(func)

    def run(self, **kwargs: Any) -> str:
        result = self._func(**kwargs)
        return str(result) if result is not None else ""


def tool(
    description: str | None = None,
    name: str | None = None,
    args_schema: type[BaseModel] | None = None,
) -> Callable:
    """Decorator to turn a function into a Tool.

    Usage:
        @tool(description="Search products by query")
        def search_products(query: str) -> str:
            ...
    """

    def decorator(func: Callable) -> FunctionTool:
        return FunctionTool(
            func=func,
            name=name or func.__name__,
            description=description or func.__doc__ or "",
            args_schema=args_schema,
        )

    return decorator


def _schema_from_function(func: Callable) -> type[BaseModel]:
    """Auto-generate a Pydantic model from function signature."""
    hints = get_type_hints(func)
    sig = inspect.signature(func)
    fields: dict[str, Any] = {}

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue
        annotation = hints.get(param_name, str)
        if param.default is inspect.Parameter.empty:
            fields[param_name] = (annotation, ...)
        else:
            fields[param_name] = (annotation, Field(default=param.default))

    return create_model(f"{func.__name__}_args", **fields)
