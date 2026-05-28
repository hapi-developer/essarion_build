"""The plan-first reasoning loop, wrapped in a REPL.

The core flow for one task:

  1. user types task
  2. picker picks 3-5 relevant skills  (token saver)
  3. reason() → plan, tradeoffs, verdict  (PLAN PHASE — user sees this)
  4. user approves / edits / cancels
  5. if approved → generate() → code, defense  (DRAFT PHASE)
  6. if selfcheck rejected AND an escalate model is set → re-run with escalate model
  7. show diff; user applies / saves / discards
  8. record turn; loop

The agent uses the SDK's reason()/generate() so every reasoning-loop
improvement we make to the SDK shows up here too.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .. import (
    Context,
    LiteRuntime,
    Reasoning,
    Usage,
    build_provider,
    generate,
    reason,
    stream_generate,
)
from .. import workflows
from .._context import RepoFile
from ._session import (
    Session,
    TaskTurn,
    estimate_cost_usd,
)
from ._skill_picker import explain_pick, pick_skills
from . import _tools, _ui
from ._commands import dispatch as dispatch_command


# Regex that finds path-shaped tokens in a user message. Used by the
# auto-attach step to load files the user clearly wants the agent to see.
_PATH_RE = re.compile(r"(?:\b|^)([\w/._-]+\.(?:py|ts|tsx|js|jsx|md|sql|toml|yml|yaml|json|rs|go|java|kt|rb|sh))(?:\b|$)")
# Directory references — words that look like "src/auth/" or "tests/".
_DIR_RE = re.compile(r"(?:\b|^)((?:[\w._-]+/)+)(?:\b|$|\s)")
# How many files to auto-attach from a referenced directory.
_DIR_AUTOLOAD_MAX = 8


def _autoload_files(task: str, cwd: Path, ctx: Context, console) -> list[str]:
    """If the user names any files or directories in their task, load them
    into the context.

    Files mentioned by name (`src/auth.py`) attach individually.
    Directories mentioned (`src/auth/`) attach up to `_DIR_AUTOLOAD_MAX`
    files from inside.
    """
    loaded: list[str] = []
    seen_paths: set[str] = set()

    for match in _PATH_RE.finditer(task):
        rel = match.group(1)
        path = cwd / rel
        if not path.is_file() or rel in seen_paths:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if len(content) > 200_000:
            content = content[:200_000] + "\n... (truncated)"
        ctx.repo_files.append(RepoFile(path=rel, content=content))
        loaded.append(rel)
        seen_paths.add(rel)

    # Directory references — attach the first N files inside, skipping VCS/build dirs.
    skip_parts = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}
    for match in _DIR_RE.finditer(task):
        rel = match.group(1).rstrip("/")
        d = cwd / rel
        if not d.is_dir():
            continue
        count_for_dir = 0
        for p in sorted(d.rglob("*")):
            if not p.is_file():
                continue
            if any(part in skip_parts for part in p.parts):
                continue
            try:
                rel_p = p.relative_to(cwd).as_posix()
            except ValueError:
                continue
            if rel_p in seen_paths:
                continue
            try:
                content = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if len(content) > 100_000:
                content = content[:100_000] + "\n... (truncated)"
            ctx.repo_files.append(RepoFile(path=rel_p, content=content))
            loaded.append(rel_p)
            seen_paths.add(rel_p)
            count_for_dir += 1
            if count_for_dir >= _DIR_AUTOLOAD_MAX:
                break

    if loaded:
        console.print(
            f"[meta]auto-loaded:[/meta] " + " ".join(f"[skill]{p}[/skill]" for p in loaded[:12])
            + (f" [meta](+ {len(loaded) - 12} more)[/meta]" if len(loaded) > 12 else "")
        )
    return loaded


def _pick_skills_for(task: str, mode: str) -> tuple[list[str], str]:
    """Apply the session's skills mode to a task."""
    if mode == "none":
        return [], ""
    if mode == "all":
        from .. import list_skills

        return list_skills(), "all skills loaded (mode=all)"
    picks = pick_skills(task)
    return picks, explain_pick(task, picks)


def _record_phase_usage(turn: TaskTurn, session: Session, usage: Usage) -> None:
    """Roll a Usage into the turn and update the session totals."""
    turn.usage = turn.usage + usage
    turn.cost_usd += estimate_cost_usd(session.provider, session.model, usage)


class _BudgetExceeded(RuntimeError):
    """Raised when a turn's projected spend would cross the session budget."""


def _check_budget(console, session: Session, turn: TaskTurn) -> bool:
    """Return False (and print a warning) if the budget cap is enforced and
    we're past it. The agent will skip the next phase."""
    if not session.budget_usd:
        return True
    if session.total_cost_usd + turn.cost_usd > session.budget_usd:
        console.print(
            f"[cost.over]budget cap reached "
            f"(${session.total_cost_usd + turn.cost_usd:.4f} > "
            f"${session.budget_usd:.2f}); halting this turn.[/cost.over]"
        )
        console.print(
            "[hint]raise it with `/budget <new>` and re-run the task, "
            "or switch to a cheaper model with `/model`.[/hint]"
        )
        return False
    return True


def _build_context(
    task: str, *, session: Session, cwd: Path, console
) -> tuple[Context, list[str], str]:
    """Build the Context for one turn. Returns (ctx, picks, reason_for_picks)."""
    from ._inline_tools import _INLINE_ALLOW
    from ._memory import inject_into_context, load_memory

    ctx = Context()
    picks, why = _pick_skills_for(task, session.skills_mode)
    if picks:
        ctx.with_skills(picks)
    # Inject project memory (free signal — no model call).
    try:
        memory = load_memory(cwd)
        inject_into_context(memory, ctx)
    except Exception:  # noqa: BLE001 - memory must never break a turn
        pass
    # Inline tool manifest — short note telling the model which tools
    # it can call during planning to read files / search code.
    ctx.add_note(
        "If you need to read code before planning, emit a "
        "<tool_call name=\"NAME\">JSON args</tool_call> tag inside your <plan>. "
        f"Read-only tools available: {', '.join(sorted(_INLINE_ALLOW))}. "
        "The agent will run them and re-plan with the results in context. "
        "Don't use this for write_file/run_shell/start_background — those "
        "happen via the user-approved apply step."
    )
    _autoload_files(task, cwd, ctx, console)
    return ctx, picks, why


def _make_runtime(provider: str, model: str) -> LiteRuntime:
    """Build a fresh runtime each turn so the agent picks up /model swaps.

    Wraps the underlying builder so a missing API key becomes a typed,
    actionable error instead of a generic RuntimeError.
    """
    try:
        prov = build_provider(name=provider, api_key=None, model=model)
    except RuntimeError as e:
        # The SDK raises RuntimeError("OPENROUTER_API_KEY is not set ...")
        # — wrap so the agent path can surface a friendlier message.
        raise _MissingKeyError(str(e)) from e
    return LiteRuntime(prov)


class _MissingKeyError(RuntimeError):
    """Distinguishable from a network/HTTP RuntimeError. Caught and rendered
    by the phase runners with an actionable hint."""


def _looks_like_reject(verdict: str) -> bool:
    """Heuristic: did the selfcheck say "do not ship"?"""
    text = (verdict or "").lower()
    return "do not ship" in text or "not ship without" in text


def _run_plan_phase(
    console, session: Session, ctx: Context, task: str, turn: TaskTurn
) -> Reasoning | None:
    """Run reason() and render the plan panel. Returns the Reasoning or None on err.

    If the model emits read-only `<tool_call>` tags inline (read_file,
    grep, list_dir, find_files, glob), the agent executes them, folds
    the results back into the context as notes, and re-plans. Loops up
    to `_MAX_TOOL_ROUNDS` times.
    """
    from ._inline_tools import (
        _MAX_TOOL_ROUNDS,
        applied_results,
        fold_into_context,
        has_tool_calls,
        tool_results_summary,
    )

    _ui.render_phase_header(console, "plan")

    def _do_reason() -> Reasoning | None:
        with console.status(
            "[brand]thinking…[/brand] [hint](plan → selfcheck)[/hint]",
            spinner="dots",
        ):
            try:
                return reason(
                    task,
                    context=ctx,
                    _runtime=_make_runtime(session.provider, session.model),
                    max_tokens=session.max_tokens,
                )
            except _MissingKeyError as e:
                console.print(f"[err]plan failed: missing API key[/err]")
                console.print(f"[hint]{e}[/hint]")
                console.print(
                    "[hint]export the key in your shell, or switch model with "
                    "`/model <provider>/<model>` (try `/model ollama/llama3.2` for local).[/hint]"
                )
                return None
            except Exception as e:  # noqa: BLE001
                console.print(f"[err]plan failed: {type(e).__name__}: {e}[/err]")
                return None

    r = _do_reason()
    if r is None:
        return None

    # If the plan contains read-only tool calls, execute them and re-plan.
    rounds = 0
    while rounds < _MAX_TOOL_ROUNDS and has_tool_calls(r.plan):
        _record_phase_usage(turn, session, r.usage)
        with_results = applied_results(r.plan)
        results = tool_results_summary(with_results)
        if not results:
            break
        n = fold_into_context(ctx, results)
        console.print(
            f"[meta]ran[/meta] [brand]{len(results)}[/brand] [meta]tool call(s) inline; "
            f"folded {n} result(s) into context, re-planning…[/meta]"
        )
        rounds += 1
        r = _do_reason()
        if r is None:
            return None
    _record_phase_usage(turn, session, r.usage)
    _ui.render_plan(console, r.plan, r.tradeoffs, r.verdict)
    return r


def _run_draft_phase(
    console, session: Session, ctx: Context, task: str, turn: TaskTurn
):
    """Run generate(); if selfcheck rejects AND escalate is set, re-run with escalate.

    Streams the draft phase token-by-token (when stream=True on the session)
    so the user sees code as it's written.
    """
    _ui.render_phase_header(console, "draft")
    streamed = False
    if getattr(session, "stream", False):
        # Stream via the SDK's stream_generate; collect into a final Generation.
        from .. import Generation, Reasoning

        try:
            plan_text = tradeoffs_text = verdict_text = code_text = defense_text = ""
            usage = Usage()
            console.print("[hint]streaming…[/hint]")
            for ev in stream_generate(
                task,
                context=ctx,
                provider=session.provider,
                model=session.model,
                max_tokens=session.max_tokens,
            ):
                if ev.kind == "token" and ev.phase == "draft":
                    # Show the draft tokens as they arrive — that's the
                    # whole point of streaming for the agent's UX.
                    console.print(ev.text, end="", style="phase.draft")
                if ev.kind == "phase_end":
                    if ev.phase == "plan":
                        plan_text = ev.tags.get("plan", plan_text)
                        tradeoffs_text = ev.tags.get("tradeoffs", tradeoffs_text)
                        verdict_text = ev.tags.get("verdict", verdict_text)
                    elif ev.phase == "draft":
                        code_text = ev.tags.get("code", code_text)
                        console.print()  # newline after the code stream
                    elif ev.phase == "selfcheck":
                        verdict_text = ev.tags.get("verdict", verdict_text)
                        defense_text = ev.tags.get("defense", defense_text)
                if ev.kind == "usage":
                    usage = usage + ev.usage
            g = Generation(
                code=code_text,
                reasoning=Reasoning(
                    plan=plan_text,
                    tradeoffs=tradeoffs_text,
                    verdict=verdict_text,
                    usage=usage,
                ),
                defense=defense_text,
                usage=usage,
            )
            streamed = True
        except Exception as e:  # noqa: BLE001
            console.print(f"[err]draft (streamed) failed: {type(e).__name__}: {e}[/err]")
            return None
    else:
        with console.status(
            "[brand]drafting…[/brand] [hint](draft → selfcheck)[/hint]",
            spinner="dots",
        ):
            try:
                g = generate(
                    task,
                    context=ctx,
                    _runtime=_make_runtime(session.provider, session.model),
                    max_tokens=session.max_tokens,
                )
            except _MissingKeyError as e:
                console.print(f"[err]draft failed: missing API key[/err]")
                console.print(f"[hint]{e}[/hint]")
                return None
            except Exception as e:  # noqa: BLE001
                console.print(f"[err]draft failed: {type(e).__name__}: {e}[/err]")
                return None
    _record_phase_usage(turn, session, g.usage)

    if _looks_like_reject(g.reasoning.verdict) and session.escalate_model:
        console.print(
            f"[warn]selfcheck flagged the draft; escalating to "
            f"{session.escalate_model}…[/warn]"
        )
        turn.escalated = True
        with console.status(
            f"[brand]re-drafting with {session.escalate_model}…[/brand]",
            spinner="dots",
        ):
            try:
                g2 = generate(
                    task,
                    context=ctx,
                    _runtime=_make_runtime(session.provider, session.escalate_model),
                    max_tokens=session.max_tokens,
                )
            except Exception as e:  # noqa: BLE001
                console.print(
                    f"[err]escalation failed: {type(e).__name__}: {e}[/err]"
                )
                return g
        # We charge BOTH passes — the user sees the cost honestly.
        _record_phase_usage(turn, session, g2.usage)
        g = g2
    return g


def _apply_or_save(console, session: Session, turn: TaskTurn, code: str) -> None:
    """Offer to apply the code change. Tries to detect diffs vs raw code."""
    if not code.strip():
        return
    looks_like_diff = code.lstrip().startswith(("--- ", "diff ")) or "@@" in code
    if looks_like_diff:
        _ui.render_diff(console, code)
        kind = "diff"
    else:
        _ui.render_code(console, code)
        kind = "code"

    choice = _ui.prompt_approve_apply(console, kind=kind)
    if choice == "discard":
        console.print("[meta]discarded.[/meta]")
        return
    if choice == "save":
        path = _ui.prompt_text(console, "[brand]save to (path)[/brand]")
        if not path:
            console.print("[meta]skipped[/meta]")
            return
        try:
            _tools.write_file(path, code)
        except Exception as e:  # noqa: BLE001
            console.print(f"[err]save failed: {e}[/err]")
            return
        console.print(f"[ok]saved → {path}[/ok]")
        turn.files_touched.append(path)
        return
    # apply: for raw code we ask for the path; for diff we leave it to
    # the user (we don't auto-`patch` because the diff format may vary).
    if kind == "diff":
        console.print(
            "[warn]applying a diff in-place isn't supported yet — save it and "
            "use `git apply` outside the REPL.[/warn]"
        )
        return
    path = _ui.prompt_text(
        console, "[brand]apply to (path)[/brand]", default="(skip)"
    )
    if not path or path == "(skip)":
        console.print("[meta]skipped[/meta]")
        return
    try:
        _tools.write_file(path, code)
    except Exception as e:  # noqa: BLE001
        console.print(f"[err]apply failed: {e}[/err]")
        return
    console.print(f"[ok]wrote → {path}[/ok]")
    turn.files_touched.append(path)


def _maybe_handle_workflow(
    task: str, console, session: Session, ctx: Context, turn: TaskTurn
) -> bool:
    """If `task` starts with a workflow keyword, route it to workflows.* instead
    of plain reason()/generate(). Returns True if handled."""
    head = task.split(":", 1)[0].strip().lower()
    if head not in {"review", "fix-bug", "tests", "refactor", "docs",
                    "security-review", "perf-review", "pr-description", "explain"}:
        return False
    body = task.split(":", 1)[1].strip() if ":" in task else ""
    if not body:
        body = task  # fall back: the model can pick up the verb from the task
    runtime = _make_runtime(session.provider, session.model)
    _ui.render_phase_header(console, "plan")
    try:
        with console.status("[brand]workflow…[/brand]", spinner="dots"):
            if head == "review":
                r = workflows.review(body, context=ctx, _runtime=runtime)
            elif head == "security-review":
                r = workflows.security_review(body, context=ctx, _runtime=runtime)
            elif head == "perf-review":
                r = workflows.performance_review(body, context=ctx, _runtime=runtime)
            elif head == "explain":
                r = workflows.explain_code(body, context=ctx, _runtime=runtime)
            elif head == "fix-bug":
                g = workflows.fix_bug(body, context=ctx, _runtime=runtime)
                _record_phase_usage(turn, session, g.usage)
                turn.plan = g.reasoning.plan
                turn.tradeoffs = g.reasoning.tradeoffs
                turn.verdict = g.reasoning.verdict
                turn.code = g.code
                turn.defense = g.defense
                _ui.render_plan(console, g.reasoning.plan, g.reasoning.tradeoffs, g.reasoning.verdict)
                _ui.render_defense(console, g.defense)
                _apply_or_save(console, session, turn, g.code)
                return True
            elif head == "tests":
                g = workflows.write_tests(body, context=ctx, _runtime=runtime)
                _record_phase_usage(turn, session, g.usage)
                turn.plan = g.reasoning.plan
                turn.code = g.code
                _ui.render_plan(console, g.reasoning.plan, g.reasoning.tradeoffs, g.reasoning.verdict)
                _ui.render_defense(console, g.defense)
                _apply_or_save(console, session, turn, g.code)
                return True
            elif head == "refactor":
                g = workflows.refactor(body, context=ctx, _runtime=runtime)
                _record_phase_usage(turn, session, g.usage)
                turn.plan = g.reasoning.plan
                turn.code = g.code
                _ui.render_plan(console, g.reasoning.plan, g.reasoning.tradeoffs, g.reasoning.verdict)
                _ui.render_defense(console, g.defense)
                _apply_or_save(console, session, turn, g.code)
                return True
            elif head == "docs":
                g = workflows.docs(body, context=ctx, _runtime=runtime)
                _record_phase_usage(turn, session, g.usage)
                turn.code = g.code
                _ui.render_plan(console, g.reasoning.plan, g.reasoning.tradeoffs, g.reasoning.verdict)
                _apply_or_save(console, session, turn, g.code)
                return True
            elif head == "pr-description":
                g = workflows.write_pr_description(body, context=ctx, _runtime=runtime)
                _record_phase_usage(turn, session, g.usage)
                turn.code = g.code
                _ui.render_plan(console, g.reasoning.plan, g.reasoning.tradeoffs, g.reasoning.verdict)
                _apply_or_save(console, session, turn, g.code)
                return True
            else:
                return False  # unreachable
            _record_phase_usage(turn, session, r.usage)
            turn.plan = r.plan
            turn.tradeoffs = r.tradeoffs
            turn.verdict = r.verdict
            _ui.render_plan(console, r.plan, r.tradeoffs, r.verdict)
    except Exception as e:  # noqa: BLE001
        console.print(f"[err]workflow failed: {type(e).__name__}: {e}[/err]")
    return True


def _maybe_auto_verify(console, session: Session, turn: TaskTurn) -> None:
    """If the user has `[verify].auto = true` configured AND this turn
    wrote a file, run the check command and surface PASS/FAIL inline."""
    if not turn.files_touched:
        return
    from ._verify import configured_check, run_check

    cmd, auto = configured_check(session.cwd)
    if not auto or not cmd:
        return
    console.print(f"[meta]auto-verify:[/meta] [key]{cmd}[/key]")
    with console.status("[brand]verifying…[/brand]"):
        result = run_check(cmd, cwd=session.cwd)
    if result.ok:
        console.print(f"[ok]verify PASS[/ok] [meta](exit {result.exit_code})[/meta]")
        return
    from rich.panel import Panel

    console.print(
        f"[err]verify FAIL[/err] [meta](exit {result.exit_code})[/meta]"
    )
    console.print(Panel(result.head, border_style="err", padding=(0, 1)))
    console.print(
        "[hint]use /undo to revert the change, or fix forward.[/hint]"
    )


def run_turn(console, session: Session, task: str) -> None:
    """Run one full task end-to-end (the plan-first loop)."""
    from ._pricing import estimate_turn_cost_usd, format_cost

    cwd = Path(session.cwd)
    ctx, picks, why = _build_context(task, session=session, cwd=cwd, console=console)
    if picks:
        _ui.render_skills_picked(console, picks, why)

    # Pre-flight projected cost so the user sees what this turn will cost
    # before paying for it.
    tokens, projected = estimate_turn_cost_usd(
        ctx, provider=session.provider, model=session.model,
        max_tokens=session.max_tokens, n_calls=3,
    )

    # Auto-compact: if the projected cost would blow the remaining budget,
    # try shrinking the context (drop docs / repo files) to fit.
    if projected and session.budget_usd:
        remaining = max(0.0, session.budget_usd - session.total_cost_usd)
        if projected > remaining * 0.8:  # within 80% of remaining is too close
            from .. import compact

            ratio = (remaining * 0.5) / projected  # aim for half the remaining
            target_tokens = max(1000, int(tokens * ratio))
            shrunk = compact(ctx, max_tokens=target_tokens)
            new_tokens, new_projected = estimate_turn_cost_usd(
                shrunk, provider=session.provider, model=session.model,
                max_tokens=session.max_tokens, n_calls=3,
            )
            if new_projected < projected:
                ctx = shrunk
                console.print(
                    f"[warn]auto-compacted context "
                    f"({tokens:,} → {new_tokens:,} tokens, "
                    f"{format_cost(projected)} → {format_cost(new_projected)})[/warn]"
                )
                tokens, projected = new_tokens, new_projected

    cost_str = format_cost(projected) if projected else "—"
    console.print(
        f"[meta]context ~{tokens:,} tokens · projected cost: "
        f"[brand]{cost_str}[/brand][/meta]"
    )

    turn = TaskTurn(task=task, skills_used=picks)

    # 0. Workflow-prefixed shortcut: "review: src/auth.py" → workflows.review()
    if _maybe_handle_workflow(task, console, session, ctx, turn):
        session.record(turn)
        _ui.render_usage_line(
            console,
            label="turn usage",
            usage_total=turn.usage.total_tokens,
            cost_usd=turn.cost_usd,
            budget_usd=session.budget_usd,
        )
        _ui.render_footer(console, session)
        return

    # 1. PLAN phase
    r = _run_plan_phase(console, session, ctx, task, turn)
    if r is None:
        session.record(turn)
        return
    turn.plan = r.plan
    turn.tradeoffs = r.tradeoffs
    turn.verdict = r.verdict

    # 2a. Budget check before the draft phase.
    if not _check_budget(console, session, turn):
        session.record(turn)
        _ui.render_footer(console, session)
        return

    # 2. Plan approval
    choice = _ui.prompt_approve_plan(console)
    if choice == "cancel":
        console.print("[meta]cancelled.[/meta]")
        session.record(turn)
        _ui.render_usage_line(
            console,
            label="turn usage",
            usage_total=turn.usage.total_tokens,
            cost_usd=turn.cost_usd,
            budget_usd=session.budget_usd,
        )
        _ui.render_footer(console, session)
        return
    if choice == "edit":
        edited = _ui.prompt_text(
            console,
            "[brand]rewrite the plan (paste your version)[/brand]",
            default=r.plan,
        )
        if edited:
            # Stash the user's plan as a context note for the draft call.
            ctx.add_note(
                "The user has revised the plan. Use this as the authoritative plan:\n\n"
                + edited
            )
            turn.plan = edited

    # 3. DRAFT phase
    g = _run_draft_phase(console, session, ctx, task, turn)
    if g is None:
        session.record(turn)
        return
    turn.code = g.code
    turn.defense = g.defense
    if g.reasoning.verdict and g.reasoning.verdict != turn.verdict:
        turn.verdict = g.reasoning.verdict

    _ui.render_defense(console, g.defense)

    # 4. Apply / save / discard
    _apply_or_save(console, session, turn, g.code)

    # 4.5 Auto-verify if configured.
    _maybe_auto_verify(console, session, turn)

    # 5. Footer
    session.record(turn)
    _ui.render_usage_line(
        console,
        label="turn usage",
        usage_total=turn.usage.total_tokens,
        cost_usd=turn.cost_usd,
        budget_usd=session.budget_usd,
    )
    if session.total_cost_usd > session.budget_usd:
        console.print(
            f"[cost.over]budget exceeded by ${session.total_cost_usd - session.budget_usd:.4f}[/cost.over]"
        )
    _ui.render_footer(console, session)


def repl(console, session: Session) -> None:
    """The main interactive loop."""
    _tools.bind_tools(session.cwd)
    while True:
        # Show any background-task completion notices first so the user
        # sees long-running commands finish between turns.
        _ui.drain_background_notices(console)
        try:
            line = _ui.prompt_input(console)
        except KeyboardInterrupt:
            line = "/quit"
        if not line:
            continue
        cmd_result = dispatch_command(console, session, line)
        if cmd_result == "quit":
            from ._background import shutdown_manager
            from ._commands import _resolve_sessions_dir
            from ._session import save_session

            try:
                sd = _resolve_sessions_dir(session)
                path = save_session(session, sessions_dir=sd)
                console.print(f"[meta]session saved to {path}[/meta]")
            except OSError as e:
                console.print(f"[warn]could not save session: {e}[/warn]")
            shutdown_manager()  # kill non-detached background tasks
            console.print("[brand]bye.[/brand]")
            return
        if cmd_result is not None:
            continue
        # Not a slash command → treat as a task.
        run_turn(console, session, line)
