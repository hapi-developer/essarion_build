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

# Default safety cap on the number of model<->tool rounds. Generous so a full
# multi-file task (scaffold → fill in → run → fix) can finish in one turn.
_DEFAULT_MAX_STEPS = 40
# Truncate a single tool result before feeding it back, to control token spend.
_RESULT_FEEDBACK_CAP = 4000
# How many times we'll nudge the model to keep going when a step produced no
# tool call and no <done>. A transient prose-only / empty step shouldn't end a
# real task — but we cap it so a stuck model can't loop forever.
_MAX_CONSECUTIVE_NUDGES = 2

_TOOL_CALL_RE = re.compile(
    r"<tool_call\s+name\s*=\s*['\"]([^'\"]+)['\"]\s*>(.*?)</tool_call>",
    re.DOTALL,
)
_RESULT_RE = re.compile(
    r"<tool_result\s+name\s*=\s*['\"]([^'\"]+)['\"]([^>]*)>(.*?)</tool_result>",
    re.DOTALL,
)
_DONE_RE = re.compile(r"<done>(.*?)</done>", re.DOTALL)
# Structural / reasoning tags some models wrap prose in. We strip the tag
# markers from the running narration (keeping the inner text) so the agent's
# output reads like Claude Code's clean narration, not raw XML.
_NARRATION_TAG_RE = re.compile(
    r"</?(?:plan|tradeoffs|verdict|critique|code|complexity|reason|reasoning|"
    r"defense|selfcheck|thinking|scratchpad|tool_result|step|action)\b[^>]*>",
    re.IGNORECASE,
)


class ExecResult(BaseModel):
    """Outcome of an autonomous run."""

    files_touched: list[str] = Field(default_factory=list)
    # Human-readable actions taken this run, in order ("Created index.html",
    # "Ran ls -l", "Started Simple HTTP Server"). Stored on the turn for memory.
    actions: list[str] = Field(default_factory=list)
    steps: int = 0
    summary: str = ""
    stopped_reason: str = "done"  # done | max_steps | budget | no_action | error


def _infer_url(cmd: str) -> str | None:
    """Best-effort 'this server is probably reachable at …' for a background
    command, so 'how do I reach the server?' can be answered from memory."""
    m = re.search(r"(?:--port[=\s]+|-p\s+|:)(\d{2,5})\b", cmd)
    if not m:
        m = re.search(r"http\.server\s+(\d{2,5})", cmd)
    if m:
        return f"http://localhost:{m.group(1)}"
    # Common framework defaults when no explicit port is given.
    for needle, port in (("next", "3000"), ("vite", "5173"), ("flask", "5000"),
                         ("rails", "3000"), ("http.server", "8000")):
        if needle in cmd:
            return f"http://localhost:{port}"
    return None


def _system_prompt(ctx: Context, memory: str = "") -> str:
    """Build the executor's system prompt: protocol + memory + manifest + context."""
    manifest = sdk_tools.tool_manifest()
    context_block = ctx.to_prompt_block()
    protocol = (
        "You are an autonomous coding agent (like Claude Code or Codex) working "
        "directly inside a sandboxed project workspace. Accomplish the user's "
        "GOAL end to end by taking actions with tools — you can create, edit and "
        "delete files and run shell commands, and every action applies "
        "immediately to the real workspace on disk.\n\n"
        "How to act:\n"
        "- Emit one or more tool calls, each on the form:\n"
        "  <tool_call name=\"TOOL\">{\"arg\": \"value\"}</tool_call>\n"
        "- After each batch you receive <tool_result> blocks. Read them and "
        "continue. Inspect before you edit (read_file/list_dir/grep/glob), make "
        "focused changes (write_file for new files, apply_diff for edits, "
        "delete_file to remove), and verify with run_shell when you can.\n"
        "- Build the COMPLETE solution, not a stub: create every source file, "
        "config, entry point, and test the goal needs. Don't stop after one "
        "file. After writing code, run it (run_shell / start_background) to "
        "prove it works; if a command fails, read the error, fix it, and re-run.\n"
        "- If the user is just ASKING A QUESTION or chatting (not asking you to "
        "change the project), answer directly in prose and emit <done> — do NOT "
        "run tools or modify files just to answer. Use the CONVERSATION SO FAR "
        "and BACKGROUND PROCESSES below to recall what you already did.\n"
        "- Only act on real targets. Never invent placeholder values "
        "(example.com, <SERVER_IP>, foo.txt) or run commands against hosts or "
        "services you weren't asked about. If something is unknown, ask.\n"
        "- You normally work without interrupting the user. But if you hit a "
        "genuine fork only they can resolve (ambiguous requirements, a real "
        "choice between approaches), ask with:\n"
        "  <tool_call name=\"ask_user\">{\"questions\": [{\"question\": \"...\", "
        "\"header\": \"short label\", \"options\": [\"A\", \"B\", \"C\"]}]}</tool_call>\n"
        "  Up to 4 options per question (an 'Other' choice is added "
        "automatically); you may ask a few at once. Don't overuse it — only for "
        "decisions that materially change the outcome.\n"
        "- When the goal is complete (or the question answered), emit exactly:\n"
        "  <done>a one-line summary of what you did</done>"
    )
    parts = [protocol]
    if memory.strip():
        parts.append(memory.strip())
    parts.append(manifest)
    parts.append(context_block)
    return "\n\n".join(p for p in parts if p and p.strip())


def _conversation_memory(session: Session) -> str:
    """A recap of prior turns (with the concrete actions of the most recent one)
    plus live background-process state, so a follow-up — 'what did you just do?',
    'what's running?', 'how do I reach the server?' — is answered precisely from
    memory instead of blindly groping the filesystem."""
    history = getattr(session, "history", None) or []
    lines: list[str] = []
    for i, t in enumerate(history[-6:]):
        is_last = i == len(history[-6:]) - 1
        task = " ".join((t.task or "").split())[:200]
        summary = " ".join((getattr(t, "summary", "") or getattr(t, "verdict", "") or "").split())[:200]
        files = ", ".join((t.files_touched or [])[:10])
        entry = f'- You asked: "{task}"'
        if summary:
            entry += f" → {summary}"
        if files:
            entry += f" [files: {files}]"
        # For the MOST RECENT turn, spell out exactly what was done so the user
        # can ask precise follow-ups about it.
        actions = getattr(t, "actions", None) or []
        if is_last and actions:
            shown = actions[:14]
            entry += "\n    actions just taken:\n" + "\n".join(f"      · {a}" for a in shown)
            if len(actions) > len(shown):
                entry += f"\n      · (+{len(actions) - len(shown)} more)"
        lines.append(entry)

    # Live background-process state: running ones (with a reachable-URL hint for
    # servers) and the most recent finished ones (with exit status).
    running: list[str] = []
    finished: list[str] = []
    try:
        from . import _background

        for bt in _background.current_manager().poll_all():
            cmd = getattr(bt, "cmd", "") or ""
            if getattr(bt, "is_running", False):
                url = _infer_url(cmd)
                tail = f" — likely reachable at {url}" if url else ""
                running.append(f"- [{bt.id}] {bt.name}: `{cmd}` (running{tail})")
            else:
                code = getattr(bt, "exit_code", None)
                status = getattr(bt, "status", "finished")
                finished.append(
                    f"- [{bt.id}] {bt.name}: `{cmd}` ({status}"
                    + (f", exit {code}" if code is not None else "") + ")"
                )
    except Exception:  # noqa: BLE001 - memory must never break a turn
        pass

    blocks: list[str] = []
    if lines:
        blocks.append("CONVERSATION SO FAR (earlier turns this session, oldest→newest):\n" + "\n".join(lines))
    if running:
        blocks.append("BACKGROUND PROCESSES still running (you started these):\n" + "\n".join(running))
    if finished:
        blocks.append("RECENTLY FINISHED background tasks:\n" + "\n".join(finished[-4:]))
    return "\n\n".join(blocks)


# Per-tool verb + how to show its result in the compact action line.
def _verb_for(name: str, existed: bool) -> str:
    if name == "write_file":
        return "Updated" if existed else "Created"
    return {
        "apply_diff": "Edited", "delete_file": "Deleted", "read_file": "Read",
        "list_dir": "Listed", "grep": "Searched", "find_files": "Searched",
        "glob": "Searched", "run_shell": "Ran", "start_background": "Started",
        "check_background": "Checked task", "wait_background": "Waited on task",
        "kill_background": "Killed task", "list_background": "Listed tasks",
    }.get(name, f"Used {name}")


def _target_for(name: str, args: dict[str, Any]) -> str:
    if name in {"write_file", "apply_diff", "delete_file", "read_file"}:
        return str(args.get("path", ""))
    if name == "list_dir":
        return str(args.get("path", "."))
    if name in {"grep", "find_files", "glob"}:
        return str(args.get("pattern", ""))
    if name == "run_shell":
        return str(args.get("cmd", args.get("command", "")))
    if name == "start_background":
        return str(args.get("name") or args.get("cmd", ""))
    return str(args.get("task_id", ""))


def _edit_diff(args: dict[str, Any], max_lines: int = 6) -> str:
    """A tiny -old/+new diff for an apply_diff edit, for the compact view."""
    old = str(args.get("old", ""))
    new = str(args.get("new", ""))
    if not old and not new:
        return ""
    lines = [f"-{ln}" for ln in old.splitlines()[:max_lines]]
    lines += [f"+{ln}" for ln in new.splitlines()[:max_lines]]
    return "\n".join(lines)


# Tools whose (successful) output is worth showing as a short collapsed tail.
_SHOW_OUTPUT = {
    "run_shell", "start_background", "check_background", "wait_background",
    "kill_background", "list_background",
}


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


def _attach_images(feedback: str, session: Session):
    """If a computer-use screenshot was captured this step AND the model can see
    images, return multimodal content (text + image blocks) so the model
    actually sees the screen. Otherwise return the plain feedback string.

    This is the only place the act→observe loop becomes multimodal; everything
    else stays text, on the cheap text-only path."""
    try:
        from ..computer import drain_pending_images, model_supports_vision
        from .._content import image_block, text_block
    except Exception:  # noqa: BLE001
        return feedback
    images = drain_pending_images()
    if not images:
        return feedback
    if not model_supports_vision(session.provider, session.model):
        # Captured but the model can't see it; don't send blind, just note it.
        return feedback + "\n(a screenshot was captured but the current model can't view images.)"
    content = [text_block(feedback)]
    for data, media_type in images:
        content.append(image_block(data, media_type))
    return content


def _narration(text: str, *, limit: int = 400) -> str:
    """The model's prose with tool/done tags stripped — shown so the user can
    follow the agent's reasoning, like Claude Code's running narration.

    `limit` caps the length: short for a lead-in before tool calls, large for an
    answer-only step (a reply to a question) so the full answer isn't clipped.
    """
    stripped = _TOOL_CALL_RE.sub("", text)
    stripped = _DONE_RE.sub("", stripped)
    # Drop structural tag markers (keep their inner text) so wrapped reasoning
    # reads as plain prose rather than raw XML.
    stripped = _NARRATION_TAG_RE.sub("", stripped)
    # Rich markup uses [tag] syntax; drop brackets so prose can't mangle it.
    stripped = stripped.replace("[", "").replace("]", "")
    collapsed = " ".join(stripped.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1].rstrip() + "…"


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
    system = _system_prompt(ctx, memory=_conversation_memory(session))
    if extra_system.strip():
        system += "\n\n" + extra_system.strip()
    user = f"GOAL:\n{goal.strip()}\n"
    if plan.strip():
        user += f"\nAPPROVED PLAN:\n{plan.strip()}\n"
    user += "\nBegin now — take the first actions."
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]

    result = ExecResult()
    touched: list[str] = []
    actions_log: list[str] = []  # human-readable recap of what we did, for memory
    nudges = 0  # consecutive no-action steps we've prodded the model through

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
            # Live "Thinking…" spinner (the rotating |/-\ bar) while the model
            # works, so a step never looks frozen during the model call.
            with console.status("[brand]Thinking…[/brand]", spinner="line"):
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

        calls = _parse_calls(text)
        done = _DONE_RE.search(text)

        # Answer-only step (no tool calls) → it's a reply/summary to the user, so
        # show it in full. A step that also calls tools → just a short lead-in.
        narration = _narration(text, limit=4000 if not calls else 320)
        if narration:
            console.print(f"[agent]{narration}[/agent]")

        if not calls:
            if done:
                # Clean finish — the model signalled the goal is complete.
                result.summary = done.group(1).strip()
                result.stopped_reason = "done"
                break
            # No tool call and no <done>. Don't give up on the task because of
            # one prose-only step — nudge the model to either act or finish, up
            # to a small cap, then stop so a stuck model can't loop forever.
            if nudges < _MAX_CONSECUTIVE_NUDGES:
                nudges += 1
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content": (
                    "You didn't take an action or finish. If the goal is fully "
                    "complete and verified, emit <done>summary</done> now. "
                    "Otherwise keep going: emit the next <tool_call> to make "
                    "progress (create/edit files, run commands)."
                )})
                continue
            result.summary = narration
            result.stopped_reason = "no_action"
            break

        # We took at least one action this step — reset the stall counter.
        nudges = 0

        # Run each requested tool, render it compactly, collect results to feed back.
        result_blocks: list[str] = []
        for name, raw_args in calls:
            args = _parse_args(raw_args)

            # ask_user is interactive — handled here (not via the headless
            # registry) so it can prompt the real user and feed the choice back.
            if name == "ask_user":
                body = _ui.ask_user_questions(console, args)
                actions_log.append("Asked the user a question")
                result_blocks.append(f'<tool_result name="ask_user">{body}</tool_result>')
                continue

            existed = name == "write_file" and (Path(session.cwd) / str(args.get("path", ""))).exists()
            ok, body = _run_one(name, raw_args, allow)

            verb = _verb_for(name, existed)
            target = _target_for(name, args)
            diff = _edit_diff(args) if (name == "apply_diff" and ok) else ""
            show_output = (not ok) or name in _SHOW_OUTPUT or name.startswith(("browser_", "desktop_"))
            _ui.render_action(
                console, verb=verb, target=target, ok=ok, diff=diff,
                output=body if show_output else "",
            )
            actions_log.append(f"{verb} {target}".strip() + ("" if ok else " (failed)"))
            if ok and name in _MUTATING:
                path = args.get("path")
                if path and path not in touched:
                    touched.append(path)
            fed = body if len(body) <= _RESULT_FEEDBACK_CAP else body[:_RESULT_FEEDBACK_CAP] + "\n…(truncated)"
            err_attr = "" if ok else ' error="true"'
            result_blocks.append(f'<tool_result name="{name}"{err_attr}>{fed}</tool_result>')

        messages.append({"role": "assistant", "content": text})
        feedback = (
            "\n".join(result_blocks)
            + "\n\nContinue. Emit <done>summary</done> when the goal is fully complete."
        )
        messages.append({"role": "user", "content": _attach_images(feedback, session)})

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
    result.actions = actions_log
    result.steps = step
    if result.summary and result.stopped_reason == "done":
        console.print(f"[ok]✓ {result.summary}[/ok]")
    return result
