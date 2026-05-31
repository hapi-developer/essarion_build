"""Lightweight tool-use surface for the reasoning loop.

The Provider seam is intentionally simple — text in, text out — but many
real coding tasks need the model to look something up. This module
provides a *deterministic*, *opt-in* tool layer that runs **before** the
reasoning loop: the user declares tools, the model emits `<tool_call>`
tags during its plan, the runtime evaluates them, and the results are
woven into the next provider call.

Why pre-call instead of streaming-call interception? Two reasons:
1. It works on every provider, including ones without native tool use.
2. It keeps the SDK provider-agnostic — the contract is purely about
   the model's textual output.

This is NOT a substitute for native tool use on providers that support
it. For agent loops with many turns and side effects, build directly on
`Provider.complete()`. This is the small-tool case: "look up the schema",
"run this query", "fetch this URL".

Usage:

    from essarion_build.tools import Tool, register_tool, run_tools_in_plan

    @register_tool("read_file")
    def _read(path: str) -> str:
        return open(path).read()

    @register_tool("git_log")
    def _git_log(n: int = 10) -> str:
        return subprocess.check_output(["git", "log", "-n", str(n)]).decode()

    plan_text = "<plan>1. Need the file. <tool_call name='read_file'>{\"path\": \"src/foo.py\"}</tool_call> 2. Etc.</plan>"
    evaluated = run_tools_in_plan(plan_text)
    # evaluated now contains <tool_result>...</tool_result> in place of <tool_call>
"""

from __future__ import annotations

import inspect
import json
import re
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict


ToolFn = Callable[..., Any]


class Tool(BaseModel):
    """One registered tool: name + zero-arg-or-kwarg callable + description."""

    # We store the callable outside the pydantic model because functions
    # aren't friendly to pydantic v2 validation.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str = ""


_TOOLS: dict[str, ToolFn] = {}
_TOOL_DESCRIPTIONS: dict[str, str] = {}


def register_tool(name: str, *, description: str = "") -> Callable[[ToolFn], ToolFn]:
    """Decorator: register `fn` as a tool the model can call.

    The function must accept keyword arguments only (the JSON inside
    `<tool_call>` is treated as a kwargs dict) and return a stringifiable
    result. Exceptions are caught and surfaced as an error message in the
    `<tool_result>` body.
    """

    def deco(fn: ToolFn) -> ToolFn:
        _TOOLS[name] = fn
        _TOOL_DESCRIPTIONS[name] = description or (fn.__doc__ or "").strip()
        return fn

    return deco


def unregister_tool(name: str) -> None:
    _TOOLS.pop(name, None)
    _TOOL_DESCRIPTIONS.pop(name, None)


def list_tools() -> list[Tool]:
    return [
        Tool(name=n, description=_TOOL_DESCRIPTIONS.get(n, ""))
        for n in sorted(_TOOLS)
    ]


_TOOL_CALL_RE = re.compile(
    r"<tool_call\s+name\s*=\s*['\"]([^'\"]+)['\"]\s*>(.*?)</tool_call>",
    re.DOTALL,
)

# Common arg-name guesses → the tool's real parameter. Real models reach for
# natural names (run_shell "command" instead of "cmd"); we accept both so a
# good action isn't dropped over a synonym.
_ARG_ALIASES: dict[str, dict[str, str]] = {
    "run_shell": {"command": "cmd", "shell": "cmd", "script": "cmd", "cmd_line": "cmd"},
    "start_background": {"command": "cmd", "shell": "cmd"},
}


# Sibling `<key>value</key>` tags inside a tool-call body. Non-greedy + a
# backreference, so any nested tags inside a value (e.g. HTML in "content")
# are absorbed into that value rather than parsed as extra args.
_KV_TAG_RE = re.compile(r"<([A-Za-z_][A-Za-z0-9_]*)\s*>(.*?)</\1\s*>", re.DOTALL)


def _clean_tag_value(v: str) -> str:
    # Multi-line block (a file body): drop a single leading newline from
    # `<content>\n…`, keep the rest verbatim. Scalars: strip surrounding space.
    return v[1:] if v.startswith("\n") else (v if "\n" in v else v.strip())


def coerce_tool_args(raw: str) -> dict[str, Any]:
    """Parse the args from a `<tool_call>` body, tolerating what real models
    actually emit:

    * **JSON** — ``{"path": "...", "content": "..."}``; with ``strict=False`` so
      literal newlines/tabs inside a string value (a code file) are allowed.
    * **XML-style child tags** — ``<path>…</path><content>…</content>`` — which
      Claude-family models prefer for multi-line file bodies (no JSON escaping).
    * a surrounding markdown code fence (```json … ```).

    Returns a kwargs dict; raises ValueError/JSONDecodeError if it's neither.
    """
    raw = (raw or "").strip()
    if not raw:
        return {}
    if raw.startswith("```"):
        raw = re.sub(r"^```[A-Za-z0-9_-]*[ \t]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw).strip()

    # JSON form first.
    if raw[:1] in "{[":
        try:
            parsed = json.loads(raw, strict=False)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
        if parsed is not None:
            raise ValueError(f"args must be a JSON object, got {type(parsed).__name__}")

    # XML-child form (the common shape for multi-line content).
    kv = {m.group(1): _clean_tag_value(m.group(2)) for m in _KV_TAG_RE.finditer(raw)}
    if kv:
        return kv

    # Neither matched — re-raise a clear JSON error.
    parsed = json.loads(raw, strict=False)
    if not isinstance(parsed, dict):
        raise ValueError(f"args must be a JSON object, got {type(parsed).__name__}")
    return parsed


def _normalize_kwargs(name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    aliases = _ARG_ALIASES.get(name)
    if not aliases:
        return kwargs
    return {aliases.get(k, k): v for k, v in kwargs.items()}


def _signature_str(fn: ToolFn) -> str:
    """A compact `arg, optional=default` signature for the tool manifest, so the
    model uses the EXACT parameter names instead of guessing."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return ""
    parts: list[str] = []
    for p in sig.parameters.values():
        if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if p.default is inspect.Parameter.empty:
            parts.append(p.name)
        else:
            parts.append(f"{p.name}={p.default!r}")
    return ", ".join(parts)


def _format_result(name: str, body: Any) -> str:
    return f"<tool_result name=\"{name}\">{body}</tool_result>"


def _format_error(name: str, error: str) -> str:
    return f"<tool_result name=\"{name}\" error=\"true\">{error}</tool_result>"


def run_tools_in_plan(text: str, *, allow: set[str] | None = None) -> str:
    """Replace every `<tool_call …>JSON args</tool_call>` in `text` with the
    matching tool's `<tool_result>…</tool_result>`.

    `allow`, if set, restricts which tools can be called (security boundary
    when running against untrusted plan output). Unknown / disallowed tools
    are replaced with an error result rather than left intact, so the model
    can't smuggle an unevaluated `<tool_call>` past the runtime.

    Returns a new string. Does not mutate the registry.
    """

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        raw_args = match.group(2).strip()
        if allow is not None and name not in allow:
            return _format_error(name, f"tool {name!r} not in allow-list")
        fn = _TOOLS.get(name)
        if fn is None:
            return _format_error(name, f"tool {name!r} not registered")
        kwargs: dict[str, Any]
        try:
            kwargs = coerce_tool_args(raw_args)
        except (json.JSONDecodeError, ValueError) as e:
            return _format_error(name, f"args JSON invalid: {e}")
        kwargs = _normalize_kwargs(name, kwargs)
        try:
            result = fn(**kwargs)
        except Exception as e:  # noqa: BLE001 - surface to model, don't crash
            return _format_error(name, f"{type(e).__name__}: {e}")
        return _format_result(name, result)

    return _TOOL_CALL_RE.sub(_sub, text)


def tool_manifest() -> str:
    """A short summary of registered tools to inject into a Context note.

    Use when you want the model to know what tools are available before
    it starts planning. Example:

        ctx = Context().with_all_skills().add_note(tool_manifest())
    """
    if not _TOOLS:
        return "No tools are registered."
    lines = [
        "Tools available. Call one with a JSON object of arguments using EXACTLY "
        "these parameter names:",
        '  <tool_call name="TOOL">{"arg": "value"}</tool_call>',
        "",
    ]
    for name in sorted(_TOOLS):
        sig = _signature_str(_TOOLS[name])
        desc = (_TOOL_DESCRIPTIONS.get(name, "") or "").split("\n", 1)[0].strip()
        head = f"- {name}({sig})"
        lines.append(f"{head} — {desc}" if desc else head)
    return "\n".join(lines)


__all__ = [
    "Tool",
    "register_tool",
    "unregister_tool",
    "list_tools",
    "run_tools_in_plan",
    "tool_manifest",
    "coerce_tool_args",
]
