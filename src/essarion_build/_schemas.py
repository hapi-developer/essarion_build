"""JSON-schema mode: get structured output instead of free text.

`generate_json(task, schema=...)` asks the model to emit a JSON object
matching a Pydantic model (or a raw JSON schema dict). The runtime
validates it post-hoc and re-prompts once if the output fails
validation. This is the right tool when you want:

- a function-call-style structured response without provider-native
  function calling
- typed access to the generated payload in Python
- automatic schema documentation injected into the prompt

It rides on the same `reason` → `draft` → `selfcheck` loop; the only
difference is the `<code>` tag's body must parse as JSON matching the
schema. The system prompt picks up an extra instruction explaining what
"matching" means.
"""

from __future__ import annotations

import json
from typing import Any, Type, TypeVar

from pydantic import BaseModel, ValidationError

from ._context import Context
from ._generate import Generation, generate
from ._providers import Usage
from ._reasoning import Reasoning
from ._runtime import Runtime
from .exceptions import EssarionError


class SchemaValidationError(EssarionError):
    """The model's output did not validate against the requested schema even
    after one repair attempt."""


T = TypeVar("T", bound=BaseModel)


def _schema_text(schema: dict[str, Any] | Type[BaseModel]) -> str:
    """Render a schema as compact JSON for prompt injection."""
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return json.dumps(schema.model_json_schema(), indent=2)
    return json.dumps(schema, indent=2)


def _instructions(schema_text: str) -> str:
    return (
        "Your <code> tag MUST contain a single JSON object that "
        "validates against this JSON schema. Do not wrap the JSON in "
        "markdown fences; just emit raw JSON inside <code>...</code>.\n\n"
        f"Schema:\n{schema_text}"
    )


def generate_json(
    task: str,
    *,
    schema: dict[str, Any] | Type[BaseModel],
    context: Context | None = None,
    runtime: str | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    _runtime: Runtime | None = None,
) -> tuple[dict[str, Any], Generation]:
    """Like `generate()` but the code field must validate against `schema`.

    Returns a `(parsed_dict, raw_generation)` tuple. Raises
    `SchemaValidationError` if the output cannot be made to validate.
    """
    ctx = context.model_copy(deep=True) if context is not None else Context()
    ctx.add_note(_instructions(_schema_text(schema)))

    g = generate(
        task,
        context=ctx,
        runtime=runtime,
        provider=provider,
        api_key=api_key,
        model=model,
        max_tokens=max_tokens,
        _runtime=_runtime,
    )
    parsed, error = _try_parse(g.code, schema)
    if error is None:
        return parsed, g

    # One repair pass: re-frame the task with the validation error.
    repair_task = (
        f"{task}\n\n"
        f"Your previous output failed JSON-schema validation: {error}\n"
        "Emit a new <code> tag containing a JSON object that fixes the issue."
    )
    g2 = generate(
        repair_task,
        context=ctx,
        runtime=runtime,
        provider=provider,
        api_key=api_key,
        model=model,
        max_tokens=max_tokens,
        _runtime=_runtime,
    )
    parsed, error = _try_parse(g2.code, schema)
    if error is None:
        # Aggregate usage from both passes.
        g2.usage = g2.usage + g.usage
        g2.reasoning.usage = g2.usage
        return parsed, g2
    raise SchemaValidationError(
        f"Model output still failed schema validation after repair: {error}. "
        f"Last output: {g2.code[:500]}"
    )


def _try_parse(
    raw: str, schema: dict[str, Any] | Type[BaseModel]
) -> tuple[dict[str, Any], str | None]:
    """Return (parsed_dict_or_empty, error_message_or_None)."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        return {}, f"not valid JSON: {e}"
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        try:
            schema.model_validate(parsed)
        except ValidationError as e:
            return parsed, f"pydantic validation: {e}"
        return parsed, None
    # Raw schema dict: do a minimal type check at the top level.
    if not isinstance(parsed, dict):
        return {}, f"top-level value must be a JSON object, got {type(parsed).__name__}"
    required = schema.get("required") or []
    missing = [k for k in required if k not in parsed]
    if missing:
        return parsed, f"missing required keys: {missing}"
    return parsed, None


async def agenerate_json(
    task: str,
    *,
    schema: dict[str, Any] | Type[BaseModel],
    context: Context | None = None,
    runtime: str | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    _runtime: Any | None = None,
) -> tuple[dict[str, Any], "Generation"]:
    """Async sibling of `generate_json`."""
    from ._async_api import agenerate

    ctx = context.model_copy(deep=True) if context is not None else Context()
    ctx.add_note(_instructions(_schema_text(schema)))

    g = await agenerate(
        task,
        context=ctx,
        runtime=runtime,
        provider=provider,
        api_key=api_key,
        model=model,
        max_tokens=max_tokens,
        _runtime=_runtime,
    )
    parsed, error = _try_parse(g.code, schema)
    if error is None:
        return parsed, g

    repair_task = (
        f"{task}\n\n"
        f"Your previous output failed JSON-schema validation: {error}\n"
        "Emit a new <code> tag containing a JSON object that fixes the issue."
    )
    g2 = await agenerate(
        repair_task,
        context=ctx,
        runtime=runtime,
        provider=provider,
        api_key=api_key,
        model=model,
        max_tokens=max_tokens,
        _runtime=_runtime,
    )
    parsed, error = _try_parse(g2.code, schema)
    if error is None:
        g2.usage = g2.usage + g.usage
        g2.reasoning.usage = g2.usage
        return parsed, g2
    raise SchemaValidationError(
        f"Model output still failed schema validation after repair: {error}. "
        f"Last output: {g2.code[:500]}"
    )


__all__ = ["generate_json", "agenerate_json", "SchemaValidationError"]
