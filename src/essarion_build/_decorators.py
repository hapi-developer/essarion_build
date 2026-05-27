"""@reasoned decorator: pure registration, no runtime substitution.

The future essarion-build CLI walks the registry to find functions to reason
about and generate bodies for. In normal Python execution the decorated
function's original body runs unchanged.
"""

from __future__ import annotations

from typing import Callable, TypeVar

from pydantic import BaseModel, ConfigDict

from ._context import Context

F = TypeVar("F", bound=Callable[..., object])


class ReasonedFunction(BaseModel):
    """One entry in the @reasoned registry."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    fn: Callable[..., object]
    context: Context | None = None


_REGISTRY: list[ReasonedFunction] = []


def reasoned(
    *, context: Context | None = None
) -> Callable[[F], F]:
    """Decorator that registers `fn` for the essarion-build CLI to discover.

    Does NOT wrap or replace the function body. Calling the decorated function
    runs the original implementation as if the decorator were not present.
    """

    def deco(fn: F) -> F:
        _REGISTRY.append(ReasonedFunction(fn=fn, context=context))
        return fn

    return deco


def list_reasoned() -> list[ReasonedFunction]:
    """Snapshot of the registry. Safe to call at any time."""
    return list(_REGISTRY)


def _clear_registry_for_tests() -> None:
    """Test helper. Not part of the public API."""
    _REGISTRY.clear()
