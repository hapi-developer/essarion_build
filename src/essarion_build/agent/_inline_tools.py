"""Inline read-only tool execution during the plan phase.

The plan-first agent shows the user the plan before paying for a draft.
But the plan is only as good as the context the model has. If the user
asks about `the JWT validator` and we haven't auto-loaded `src/auth.py`,
the model can't reason from primary sources.

This module gives the model a way to request file reads / greps / lists
inline during planning. The model emits `<tool_call name="…">json</tool_call>`
tags in its plan; the agent runs them, weaves the results back as new
notes, and re-plans. We loop at most `_MAX_TOOL_ROUNDS` times so a
runaway model can't burn the budget.

Only READ-only tools are allowed inline. Write/shell/background tools
remain gated by user approval (the user types `/bg` or approves an
apply).
"""

from __future__ import annotations

import re
from typing import Iterable

from .. import Context
from .. import tools as sdk_tools


# Read-only tools the agent allows the model to call during planning.
_INLINE_ALLOW = {"read_file", "list_dir", "grep", "find_files", "glob",
                 "repo_map", "outline", "find_symbol", "recall"}

# How many rounds of "plan -> tool calls -> replan" before we stop.
_MAX_TOOL_ROUNDS = 3


# Same regex shape as the SDK's tools.py, kept local so we can scan without
# triggering substitution (we want to know if there are tool calls).
_TOOL_CALL_RE = re.compile(
    r"<tool_call\s+name\s*=\s*['\"]([^'\"]+)['\"]\s*>(.*?)</tool_call>",
    re.DOTALL,
)


def has_tool_calls(text: str) -> bool:
    return bool(_TOOL_CALL_RE.search(text))


def applied_results(text: str) -> str:
    """Replace `<tool_call>` with `<tool_result>` for the inline-allowed set.

    Disallowed tools become `<tool_result error="true">not allowed inline</tool_result>`.
    """
    return sdk_tools.run_tools_in_plan(text, allow=_INLINE_ALLOW)


def tool_results_summary(text: str) -> list[tuple[str, str]]:
    """Pull `<tool_result>` bodies out of `text` as `(name, body)` pairs."""
    out: list[tuple[str, str]] = []
    for match in re.finditer(
        r"<tool_result\s+name\s*=\s*['\"]([^'\"]+)['\"][^>]*>(.*?)</tool_result>",
        text,
        re.DOTALL,
    ):
        out.append((match.group(1), match.group(2).strip()))
    return out


def fold_into_context(ctx: Context, results: Iterable[tuple[str, str]]) -> int:
    """Add each tool result as a note in `ctx`. Returns count folded."""
    from .._windowing import head_tail_window

    n = 0
    for name, body in results:
        if not body.strip():
            continue
        body = head_tail_window(body, max_chars=8000)
        ctx.add_note(f"[tool: {name}]\n{body}")
        n += 1
    return n


__all__ = [
    "has_tool_calls",
    "applied_results",
    "tool_results_summary",
    "fold_into_context",
    "_INLINE_ALLOW",
    "_MAX_TOOL_ROUNDS",
]
