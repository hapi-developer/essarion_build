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
from .._windowing import head_tail_window
from ._changes import current_changelog
from ._permissions import ASK, DENY, PermissionPolicy
from ._session import Session, TaskTurn, estimate_cost_usd
from . import _ui


# Tools the autonomous loop may call. A superset of the read-only inline set —
# it adds the mutating + shell + background tools, because acting on disk is the
# whole point here.
AUTONOMOUS_ALLOW = {
    "read_file", "list_dir", "grep", "find_files", "glob",
    "repo_map", "outline", "find_symbol", "web_fetch",
    "write_file", "apply_diff", "edit_symbol", "delete_file", "run_shell",
    "start_background", "check_background", "wait_background",
    "kill_background", "list_background",
}
# Of those, the ones that change files on disk (for files_touched accounting).
_MUTATING = {"write_file", "apply_diff", "edit_symbol", "delete_file"}

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
    # The agent's latest checklist (todo/doing/done), if it kept one.
    todos: list[dict] = Field(default_factory=list)
    steps: int = 0
    summary: str = ""
    stopped_reason: str = "done"  # done | max_steps | budget | no_action | error


def _coerce_todos(args: dict[str, Any]) -> list[dict]:
    """Normalize update_todos args into [{text, status}] (status: todo/doing/done)."""
    raw = args.get("todos")
    out: list[dict] = []
    if isinstance(raw, list):
        for it in raw:
            if isinstance(it, dict) and str(it.get("text", "")).strip():
                status = str(it.get("status", "todo")).lower()
                out.append({"text": str(it["text"]).strip(),
                            "status": status if status in {"todo", "doing", "done"} else "todo"})
            elif isinstance(it, str) and it.strip():
                out.append({"text": it.strip(), "status": "todo"})
    return out


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
        "continue. ORIENT FIRST in an unfamiliar codebase: `repo_map` gives a "
        "ranked overview of the key symbols, `outline <file>` lists one file's "
        "symbols, and `find_symbol <name>` jumps to a definition and its "
        "callers — faster and cheaper than grepping or reading whole files. "
        "Then make focused changes: write_file for new files, apply_diff for "
        "small edits, edit_symbol to rewrite a whole function/class by name, "
        "delete_file to remove. Verify with run_shell when you can.\n"
        "- When the task is to ANALYZE, REVIEW, AUDIT or EXPLAIN a codebase "
        "(not change it): after repo_map, deliberately open the security- and "
        "concurrency-sensitive files, not just the entrypoints — tool/command "
        "execution, subprocess/shell, shared global or module-level state and "
        "caches, background/threaded/async code, and any raw-input or automation "
        "paths. Read each through three lenses: shared mutable state & "
        "concurrency, trust boundaries (shell/subprocess/untrusted input), and "
        "resource lifecycle (leaks, missing cleanup). Read enough to ground a "
        "claim, then move on — don't read the whole repo.\n"
        "- Keep your output dense and grounded. Every finding or claim cites a "
        "specific file and, when you can, a symbol or line (e.g. "
        "`_tools.py:run_shell`). Don't restate the question or echo back context "
        "you were given; lead with the answer. Prefer a tight, structured report "
        "(findings as a short list) over long prose.\n"
        "- An edit result may carry automatic feedback: a `⚠` syntax error you "
        "just introduced (fix it before moving on) or a `↔` note listing the "
        "callers of a symbol you changed or removed (go check them). Act on it.\n"
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
        "- For a multi-step task, set up a short checklist ONCE with update_todos, "
        "then call it again only when you start or finish a step (flip a single "
        "item to 'doing'/'done') — not after every action, and never re-send an "
        "unchanged list.\n"
        "  <tool_call name=\"update_todos\">{\"todos\": [{\"text\": \"Scaffold the app\", "
        "\"status\": \"doing\"}, {\"text\": \"Add tests\", \"status\": \"todo\"}]}</tool_call>\n"
        "  status is one of: todo | doing | done.\n"
        "- Some commands need approval or are blocked by the user's permission "
        "policy. If a tool result says an action was blocked, adapt (try another "
        "approach) or ask the user — do NOT just retry the same command.\n"
        "- When the goal is complete (or the question answered), emit exactly:\n"
        "  <done>a one-line summary of what you did</done>"
    )
    # Order matters for prompt caching: the stable prefix (protocol + tool
    # manifest, identical every turn) comes first so providers can cache it
    # across turns; the volatile parts (memory, picked skills, notes) come last.
    parts = [protocol, manifest]
    if memory.strip():
        parts.append(memory.strip())
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
    # Redact any secrets (keys/tokens) that leaked into a command or summary
    # before they ride along in the prompt.
    return _ui.redact_secrets("\n\n".join(blocks))


# Per-tool verb + how to show its result in the compact action line.
def _verb_for(name: str, existed: bool) -> str:
    if name == "write_file":
        return "Updated" if existed else "Created"
    return {
        "apply_diff": "Edited", "edit_symbol": "Edited", "delete_file": "Deleted",
        "read_file": "Read", "list_dir": "Listed", "grep": "Searched",
        "find_files": "Searched", "glob": "Searched", "run_shell": "Ran",
        "repo_map": "Mapped", "outline": "Outlined", "find_symbol": "Looked up",
        "web_fetch": "Fetched", "start_background": "Started",
        "check_background": "Checked task", "wait_background": "Waited on task",
        "kill_background": "Killed task", "list_background": "Listed tasks",
    }.get(name, f"Used {name}")


def _target_for(name: str, args: dict[str, Any]) -> str:
    if name in {"write_file", "apply_diff", "delete_file", "read_file", "outline"}:
        return str(args.get("path", ""))
    if name == "edit_symbol":
        return f"{args.get('symbol', '')} in {args.get('path', '')}".strip()
    if name == "find_symbol":
        return str(args.get("name", ""))
    if name == "web_fetch":
        return str(args.get("url", ""))
    if name == "repo_map":
        return str(args.get("focus", "")) or "the codebase"
    if name == "list_dir":
        return str(args.get("path", "."))
    if name in {"grep", "find_files", "glob"}:
        pat = str(args.get("pattern", ""))
        return pat if len(pat) <= 48 else pat[:47].rstrip() + "…"
    if name == "run_shell":
        return str(args.get("cmd", args.get("command", "")))
    if name == "start_background":
        return str(args.get("name") or args.get("cmd", ""))
    return str(args.get("task_id", ""))


def _diff_stat(args: dict[str, Any]) -> tuple[int, int]:
    """(added, removed) line counts for an apply_diff edit — a compact summary
    instead of dumping the code. The full change is viewable with /diff."""
    import difflib

    old = str(args.get("old", "")).splitlines()
    new = str(args.get("new", "")).splitlines()
    added = removed = 0
    for ln in difflib.unified_diff(old, new, n=0):
        if ln.startswith("+") and not ln.startswith("+++"):
            added += 1
        elif ln.startswith("-") and not ln.startswith("---"):
            removed += 1
    return added, removed


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


# Exploration budget: after this many read-only tool calls in one turn, the loop
# stops rewarding more reading and pushes the model to produce its answer/edits.
# This is the guard against the "reads forever, answers never" failure where a
# strong model burns the whole budget on context-gathering. A session can
# override it via `read_cap`; 0 there means "use this default".
_DEFAULT_READ_CAP = 25
_READ_TOOLS = {
    "read_file", "list_dir", "grep", "find_files", "glob",
    "repo_map", "outline", "find_symbol", "web_fetch",
}
# Output tokens reserved for — and spent on — the wrap-up summary when the budget
# runs out, so a capped run still returns its findings instead of nothing.
_SUMMARY_OUT_TOKENS = 400


def _content_chars(content: Any) -> int:
    """Char count of a message's content, whether plain text or multimodal blocks."""
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for b in content:
            total += len(str(b.get("text", ""))) if isinstance(b, dict) else len(str(b))
        return total
    return len(str(content))


def _estimate_call_cost_usd(
    session: Session, system: str, messages: list[dict[str, Any]], *, out_tokens: int
) -> float:
    """Worst-case USD cost of the NEXT provider call: the whole prompt we're about
    to send (system + messages, ~4 chars/token) plus `out_tokens` of output (the
    hard cap the provider can emit). Lets the loop stop BEFORE a call that would
    cross the budget, instead of detecting the overage after it's already billed."""
    prompt_tokens = (len(system) + sum(_content_chars(m.get("content")) for m in messages)) // 4
    usage = Usage(
        prompt_tokens=prompt_tokens,
        completion_tokens=out_tokens,
        total_tokens=prompt_tokens + out_tokens,
    )
    return estimate_cost_usd(session.provider, session.model, usage)


def _synthesize_summary(actions_log: list[str], todos: list[dict]) -> str:
    """A recap built purely from what we already did — no model call. The
    last-resort partial output when there isn't even budget for a summary call."""
    parts: list[str] = []
    if actions_log:
        parts.append("Stopped on budget. Done so far: " + "; ".join(actions_log[-8:]) + ".")
    else:
        parts.append("Stopped on budget before completing the goal.")
    open_items = [t.get("text", "") for t in (todos or []) if t.get("status") != "done"]
    open_items = [t for t in open_items if t]
    if open_items:
        parts.append("Still open: " + "; ".join(open_items[:6]) + ".")
    return " ".join(parts)


def _finalize_on_budget(
    console,
    session: Session,
    provider,
    system: str,
    messages: list[dict[str, Any]],
    *,
    turn: TaskTurn | None,
    result: "ExecResult",
    actions_log: list[str],
    latest_todos: list[dict],
    remaining: float,
) -> None:
    """Graceful partial output when the cap is hit. Spend the reserved headroom on
    a SHORT wrap-up so a budget-capped run still returns findings; if even that
    won't fit, synthesize a recap from the actions already taken. A cap is only
    useful if the user still gets value when it's reached."""
    console.print(
        "[cost.over]budget cap reached; wrapping up with a summary of progress "
        "so far instead of stopping empty-handed.[/cost.over]"
    )
    summary_cost = _estimate_call_cost_usd(
        session, system, messages, out_tokens=_SUMMARY_OUT_TOKENS
    )
    # Afford the wrap-up call when we have the headroom (summary_cost==0 means the
    # model is unpriced/free, e.g. ollama/stub — still worth a real summary).
    if remaining > 0 and summary_cost <= remaining:
        stop_text = (
            "\n\nSTOP — you are out of budget and must not take any more actions "
            "or read any more files. In 3-6 sentences, summarize what you found "
            "and what still needs doing, citing the specific files/symbols you "
            "saw. Put the whole summary inside <done>…</done>."
        )
        # The loop always pauses here with a trailing USER turn (the goal, or the
        # last tool-results feedback). Fold the wrap-up instruction INTO it rather
        # than appending a second user turn — providers like Anthropic reject two
        # consecutive same-role messages.
        msgs = [dict(m) for m in messages]
        if msgs and msgs[-1].get("role") == "user":
            content = msgs[-1].get("content")
            if isinstance(content, list):
                msgs[-1]["content"] = content + [{"type": "text", "text": stop_text}]
            else:
                msgs[-1]["content"] = (content if isinstance(content, str) else str(content)) + stop_text
        else:
            msgs.append({"role": "user", "content": stop_text.strip()})
        try:
            with console.status("[brand]summarizing before stopping…[/brand]", spinner="line"):
                resp = provider.complete(
                    system=system, messages=msgs, max_tokens=_SUMMARY_OUT_TOKENS
                )
            if turn is not None:
                u = getattr(resp, "usage", None) or Usage()
                turn.usage = turn.usage + u
                turn.cost_usd += estimate_cost_usd(session.provider, session.model, u)
            text = resp.text or ""
            done = _DONE_RE.search(text)
            summary = done.group(1).strip() if done else _narration(text, limit=800)
            if summary:
                result.summary = summary
                console.print(f"[agent]{summary}[/agent]")
                return
        except Exception as e:  # noqa: BLE001 - the summary is best-effort
            console.print(f"[meta](summary call failed: {type(e).__name__}; using recap)[/meta]")
    # No headroom (or the call failed) → recap from what we already did.
    synth = _synthesize_summary(actions_log, latest_todos)
    result.summary = synth
    if synth:
        console.print(f"[agent]{synth}[/agent]")


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
    policy: PermissionPolicy | None = None,
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
    policy = policy or PermissionPolicy()
    from . import _tools as _t

    yolo = bool(getattr(_t, "_AUTO_APPROVE", False))
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
    latest_todos: list[dict] = []  # the agent's running checklist
    nudges = 0  # consecutive no-action steps we've prodded the model through
    reads = 0  # read-only exploration calls made this turn (exploration budget)
    over_read_budget = False
    read_cap = session.read_cap or _DEFAULT_READ_CAP

    step = 0  # bound even if max_steps <= 0 so `result.steps = step` is safe
    for step in range(1, max_steps + 1):
        # Budget guard — pre-estimate the NEXT step and stop before a call that
        # would cross the cap, keeping enough headroom to still write a summary.
        if turn is not None and session.budget_usd:
            spent = session.total_cost_usd + turn.cost_usd
            remaining = session.budget_usd - spent
            reserve = (
                _estimate_call_cost_usd(session, system, messages, out_tokens=_SUMMARY_OUT_TOKENS)
                if remaining > 0 else 0.0
            )
            projected = _estimate_call_cost_usd(
                session, system, messages, out_tokens=session.max_tokens
            )
            if remaining <= 0 or projected > max(0.0, remaining - reserve):
                _finalize_on_budget(
                    console, session, provider, system, messages,
                    turn=turn, result=result, actions_log=actions_log,
                    latest_todos=latest_todos, remaining=remaining,
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

        # A prose-only step (no tool calls) is a reply/summary to the user → show
        # it in full, in the agent voice. A step that also acts → keep the prose
        # to a short, dim lead-in so the action lines clearly dominate.
        if calls:
            lead = _narration(text, limit=160)
            if lead:
                console.print(f"[hint]{lead}[/hint]")
            narration = ""
        else:
            narration = _narration(text, limit=4000)
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

            # update_todos maintains the agent's visible checklist. We only
            # render what changed (and nothing for a no-op call).
            if name == "update_todos":
                new_todos = _coerce_todos(args)
                _ui.render_todos(console, new_todos, latest_todos)
                latest_todos = new_todos
                result_blocks.append('<tool_result name="update_todos">todo list updated</tool_result>')
                continue

            # Permission policy: allow / ask (confirm) / deny. Reads are free;
            # shell commands are screened against the dangerous-command list.
            decision, reason = policy.decide(name, args, yolo=yolo)
            if decision == DENY or (
                decision == ASK
                and not _ui.confirm_action(console, _verb_for(name, False), _target_for(name, args), reason)
            ):
                _ui.render_action(console, verb="Blocked", target=_target_for(name, args), ok=False, output=reason)
                actions_log.append(f"Blocked {name} ({reason})".strip())
                result_blocks.append(
                    f'<tool_result name="{name}" error="true">blocked by permission policy: '
                    f"{reason}. Do not retry the same command; try another approach or ask the user."
                    "</tool_result>"
                )
                continue

            existed = name == "write_file" and (Path(session.cwd) / str(args.get("path", ""))).exists()
            ok, body = _run_one(name, raw_args, allow)

            # A shell command that ran but exited nonzero is a failure, even
            # though the tool call itself didn't raise — don't show a green ✓.
            shown_ok = ok
            if ok and name in {"run_shell", "start_background"}:
                m = re.search(r"\[exit (\d+)\]", body)
                if m and m.group(1) != "0":
                    shown_ok = False

            verb = _verb_for(name, existed)
            target = _target_for(name, args)
            diffstat = _diff_stat(args) if (name == "apply_diff" and ok) else None
            show_output = (not shown_ok) or name in _SHOW_OUTPUT or name.startswith(("browser_", "desktop_"))
            _ui.render_action(
                console, verb=verb, target=target, ok=shown_ok, diffstat=diffstat,
                output=body if show_output else "",
            )
            actions_log.append(f"{verb} {target}".strip() + ("" if shown_ok else " (failed)"))
            if ok and name in _MUTATING:
                path = args.get("path")
                if path and path not in touched:
                    touched.append(path)
            # Window (head+tail), not head-only: the end of a command's output
            # or a file body is often where the failure / the answer is.
            fed = head_tail_window(body, max_chars=_RESULT_FEEDBACK_CAP)
            err_attr = "" if shown_ok else ' error="true"'
            result_blocks.append(f'<tool_result name="{name}"{err_attr}>{fed}</tool_result>')

        # Exploration budget: count read-only calls this step; once over the cap,
        # push the model to stop gathering context and produce its answer/edits.
        reads += sum(1 for name, _ in calls if name in _READ_TOOLS)
        if not over_read_budget and reads >= read_cap:
            over_read_budget = True
            console.print(
                f"[warn]exploration budget reached ({reads} reads); asking the "
                "agent to wrap up with its answer/changes.[/warn]"
            )

        messages.append({"role": "assistant", "content": text})
        if over_read_budget:
            tail = (
                f"\n\nNote: you've made {reads} read/search calls — that is enough "
                "context. STOP reading and searching now. Either make the edits the "
                "goal needs, or — if this is an analysis/question — write your final "
                "answer grounded in what you've seen and emit <done>…</done> with it."
            )
        else:
            tail = "\n\nContinue. Emit <done>summary</done> when the goal is fully complete."
        feedback = "\n".join(result_blocks) + tail
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
    result.todos = latest_todos
    result.steps = step
    if result.summary and result.stopped_reason == "done":
        console.print(f"[ok]✓ {result.summary}[/ok]")
    return result
