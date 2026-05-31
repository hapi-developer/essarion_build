"""Autonomous execution loop — the agentic core ("auto" permission mode).

Where `run_turn`'s draft phase produces a single code blob the user saves by
hand, this drives a Claude-Code / Codex-style loop: the model is given the
goal plus the real sandboxed tools (write_file, apply_diff, delete_file,
run_shell, plus the read tools) and chains them autonomously — creating,
editing and deleting files directly on disk and running commands — until it
declares the goal done or a safety cap is hit.

Protocol (text-based tool use, works on every provider):
  - the model emits one or more
        <tool_call name="TOOL">{json kwargs}</tool_call>
    tags to act; we run them, render each as a tool_run, and feed the
        <tool_result name="TOOL">…</tool_result>
    blocks back as the next user turn.
  - when the whole goal is accomplished the model emits
        <done>one-line summary</done>

Every mutation flows through `_tools` (sandboxed to the session cwd) and is
recorded in the change log, so `/undo` and `/diff` work exactly as they do for
the hand-applied path. The loop is bounded by `max_steps` and the session
budget so a runaway model can't burn the workspace or the wallet.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from .. import Context, Usage
from .. import tools as sdk_tools
from ._changes import current_changelog
from ._session import Session, TaskTurn, estimate_cost_usd
from . import _ui


# Tools the autonomous loop may call. A superset of the read-only inline set —
# it adds the mutating + shell + background tools, because acting on disk is the
# whole point here.
AUTONOMOUS_ALLOW = {
    "read_file", "list_dir", "grep", "find_files", "glob",
    "write_file", "apply_diff", "delete_file", "run_shell",
    "start_background", "check_background", "wait_background",
    "kill_background", "list_background",
}
# Of those, the ones that change files on disk (for files_touched accounting).
_MUTATING = {"write_file", "apply_diff", "delete_file"}

# Default safety cap on the number of model<->tool rounds.
_DEFAULT_MAX_STEPS = 40
# Truncate a single tool result before feeding it back, to control token spend.
_RESULT_FEEDBACK_CAP = 4000

_TOOL_CALL_RE = re.compile(
    r"<tool_call\s+name\s*=\s*['\"]([^'\"]+)['\"]\s*>(.*?)</tool_call>",
    re.DOTALL,
)
_RESULT_RE = re.compile(
    r"<tool_result\s+name\s*=\s*['\"]([^'\"]+)['\"]([^>]*)>(.*?)</tool_result>",
    re.DOTALL,
)
_DONE_RE = re.compile(r"<done>(.*?)</done>", re.DOTALL)


class ExecResult(BaseModel):
    """Outcome of an autonomous run."""

    files_touched: list[str] = Field(default_factory=list)
    steps: int = 0
    summary: str = ""
    stopped_reason: str = "done"  # done | max_steps | budget | no_action | error


def _system_prompt(ctx: Context) -> str:
    """Build the executor's system prompt: protocol + tool manifest + context."""
    manifest = sdk_tools.tool_manifest()
    context_block = ctx.to_prompt_block()
    return (
        "You are an autonomous coding agent working directly inside a sandboxed "
        "project workspace. Accomplish the user's GOAL end to end by taking "
        "actions with tools — you can create, edit and delete files and run shell "
        "commands, and every action applies immediately to the real workspace on "
        "disk.\n\n"
        "How to act:\n"
        "- Emit one or more tool calls, each on the form:\n"
        "  <tool_call name=\"TOOL\">{\"arg\": \"value\"}</tool_call>\n"
        "- After each batch you receive <tool_result> blocks. Read them and "
        "continue. Inspect before you edit (read_file/list_dir/grep/glob), make "
        "focused changes (write_file for new files, apply_diff for edits, "
        "delete_file to remove), and verify with run_shell (run the tests/build "
        "and fix failures, then re-run) whenever you can.\n"
        "- Work autonomously and keep going across many steps. Do NOT ask the "
        "user questions or wait for approval — just do the work.\n"
        "- When the ENTIRE goal is complete and verified, emit exactly:\n"
        "  <done>a one-line summary of what you built</done>\n\n"
        f"{manifest}\n\n"
        f"{context_block}"
    )


def _parse_calls(text: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2).strip()) for m in _TOOL_CALL_RE.finditer(text)]


def _parse_args(raw: str) -> dict[str, Any]:
    """Args for display/bookkeeping — tolerant of fences and multi-line content,
    matching the executor's parser so the rendered tool call shows real args."""
    try:
        return sdk_tools.coerce_tool_args(raw)
    except Exception:  # noqa: BLE001 - display only; never fail a turn
        return {}


def _run_one(name: str, raw_args: str, allow: set[str]) -> tuple[bool, str]:
    """Execute a single tool call via the SDK registry. Returns (ok, body)."""
    call = f'<tool_call name="{name}">{raw_args}</tool_call>'
    out = sdk_tools.run_tools_in_plan(call, allow=allow)
    m = _RESULT_RE.search(out)
    if not m:
        return False, out.strip()
    is_err = 'error="true"' in (m.group(2) or "")
    return (not is_err), m.group(3).strip()


def _narration(text: str) -> str:
    """The model's prose with tool/done tags stripped — shown so the user can
    follow the agent's reasoning, like Claude Code's running narration."""
    stripped = _TOOL_CALL_RE.sub("", text)
    stripped = _DONE_RE.sub("", stripped)
    # Markup uses [tag] syntax; drop brackets so prose can't mangle it.
    stripped = stripped.replace("[", "").replace("]", "")
    return " ".join(stripped.split())[:400]


def execute(
    console,
    session: Session,
    goal: str,
    ctx: Context,
    *,
    make_runtime: Callable[[str, str], Any],
    turn: TaskTurn | None = None,
    plan: str = "",
    max_steps: int = _DEFAULT_MAX_STEPS,
    allow: set[str] | None = None,
    extra_system: str = "",
) -> ExecResult:
    """Drive tools autonomously to accomplish `goal`. Writes directly to disk.

    `make_runtime(provider, model)` yields a runtime whose `._provider` exposes
    the raw `complete()` seam (passed in so the caller's stub/patch is honored).
    `turn`, if given, accumulates usage/cost so the session budget and footer
    stay accurate.
    """
    runtime = make_runtime(session.provider, session.model)
    provider = runtime._provider  # raw text-in/text-out completion seam

    allow = allow or AUTONOMOUS_ALLOW
    system = _system_prompt(ctx)
    if extra_system.strip():
        system += "\n\n" + extra_system.strip()
    user = f"GOAL:\n{goal.strip()}\n"
    if plan.strip():
        user += f"\nAPPROVED PLAN:\n{plan.strip()}\n"
    user += "\nBegin now — take the first actions."
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]

    result = ExecResult()
    touched: list[str] = []

    for step in range(1, max_steps + 1):
        # Budget guard — stop before paying for a step we can't afford.
        if turn is not None and session.budget_usd:
            if session.total_cost_usd + turn.cost_usd > session.budget_usd:
                console.print(
                    "[cost.over]budget cap reached; stopping autonomous run.[/cost.over]"
                )
                result.stopped_reason = "budget"
                break

        try:
            resp = provider.complete(
                system=system, messages=messages, max_tokens=session.max_tokens
            )
        except Exception as e:  # noqa: BLE001 - one bad call shouldn't crash the worker
            console.print(f"[err]autonomous step failed: {type(e).__name__}: {e}[/err]")
            result.stopped_reason = "error"
            break

        text = resp.text or ""
        if turn is not None:
            usage = getattr(resp, "usage", None) or Usage()
            turn.usage = turn.usage + usage
            turn.cost_usd += estimate_cost_usd(session.provider, session.model, usage)

        narration = _narration(text)
        if narration:
            console.print(f"[agent]{narration}[/agent]")

        calls = _parse_calls(text)
        done = _DONE_RE.search(text)

        if not calls:
            # No actions this step — either we're finished or the model stalled.
            result.summary = done.group(1).strip() if done else narration
            result.stopped_reason = "done" if done else "no_action"
            break

        # Run each requested tool, render it, and collect results to feed back.
        result_blocks: list[str] = []
        for name, raw_args in calls:
            ok, body = _run_one(name, raw_args, allow)
            args = _parse_args(raw_args)
            _ui.render_tool_run(console, name, args, body, ok)
            if ok and name in _MUTATING:
                path = args.get("path")
                if path and path not in touched:
                    touched.append(path)
            fed = body if len(body) <= _RESULT_FEEDBACK_CAP else body[:_RESULT_FEEDBACK_CAP] + "\n…(truncated)"
            err_attr = "" if ok else ' error="true"'
            result_blocks.append(f'<tool_result name="{name}"{err_attr}>{fed}</tool_result>')

        messages.append({"role": "assistant", "content": text})
        messages.append({
            "role": "user",
            "content": "\n".join(result_blocks)
            + "\n\nContinue. Emit <done>summary</done> when the goal is fully complete.",
        })

        if done:
            result.summary = done.group(1).strip()
            result.stopped_reason = "done"
            break
    else:
        result.stopped_reason = "max_steps"
        console.print(
            f"[warn]reached the {max_steps}-step cap; stopping. "
            "Re-run to continue if the goal isn't complete.[/warn]"
        )

    result.files_touched = touched
    result.steps = step
    if result.summary and result.stopped_reason == "done":
        console.print(f"[ok]✓ {result.summary}[/ok]")
    return result
