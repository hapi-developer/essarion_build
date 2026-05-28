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


def _autoload_files(task: str, cwd: Path, ctx: Context, console) -> list[str]:
    """If the user names any files in their task, load them into the context.

    This is the small-but-magic auto-grounding feature: typing
    "review src/auth.py for races" auto-attaches src/auth.py — no manual
    --repo or `read_file` tool call.
    """
    loaded: list[str] = []
    for match in _PATH_RE.finditer(task):
        rel = match.group(1)
        path = cwd / rel
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if len(content) > 200_000:
            content = content[:200_000] + "\n... (truncated)"
        ctx.repo_files.append(RepoFile(path=rel, content=content))
        loaded.append(rel)
    if loaded:
        console.print(
            f"[meta]auto-loaded:[/meta] " + " ".join(f"[skill]{p}[/skill]" for p in loaded)
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


def _build_context(
    task: str, *, session: Session, cwd: Path, console
) -> tuple[Context, list[str], str]:
    """Build the Context for one turn. Returns (ctx, picks, reason_for_picks)."""
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
    _autoload_files(task, cwd, ctx, console)
    return ctx, picks, why


def _make_runtime(provider: str, model: str) -> LiteRuntime:
    """Build a fresh runtime each turn so the agent picks up /model swaps."""
    prov = build_provider(name=provider, api_key=None, model=model)
    return LiteRuntime(prov)


def _looks_like_reject(verdict: str) -> bool:
    """Heuristic: did the selfcheck say "do not ship"?"""
    text = (verdict or "").lower()
    return "do not ship" in text or "not ship without" in text


def _run_plan_phase(
    console, session: Session, ctx: Context, task: str, turn: TaskTurn
) -> Reasoning | None:
    """Run reason() and render the plan panel. Returns the Reasoning or None on err."""
    _ui.render_phase_header(console, "plan")
    with console.status(
        "[brand]thinking…[/brand] [hint](plan → selfcheck)[/hint]",
        spinner="dots",
    ):
        try:
            r = reason(
                task,
                context=ctx,
                _runtime=_make_runtime(session.provider, session.model),
                max_tokens=session.max_tokens,
            )
        except Exception as e:  # noqa: BLE001
            console.print(f"[err]plan failed: {type(e).__name__}: {e}[/err]")
            return None
    _record_phase_usage(turn, session, r.usage)
    _ui.render_plan(console, r.plan, r.tradeoffs, r.verdict)
    return r


def _run_draft_phase(
    console, session: Session, ctx: Context, task: str, turn: TaskTurn
):
    """Run generate(); if selfcheck rejects AND escalate is set, re-run with escalate."""
    _ui.render_phase_header(console, "draft")
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


_DEFAULT_CREW: list[str] = ["researcher", "implementer", "test_writer"]


def _dispatch_subagents(console, session: Session, raw_arg: str) -> None:
    """Spawn focused subagents in parallel and synthesize their findings.

    Two argument shapes:
    - `<task>`                → default crew (researcher + implementer + test_writer)
    - `role1,role2:<task>`    → explicit roles, comma-separated
    """
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.table import Table

    from ._subagent import (
        SubAgentResult,
        SubAgentSpec,
        aggregate_usage,
        run_subagents_parallel,
    )
    from ._session import TaskTurn

    # Parse roles : task.
    if ":" in raw_arg and not raw_arg.lstrip().startswith("/"):
        head, task = raw_arg.split(":", 1)
        roles = [r.strip() for r in head.split(",") if r.strip()]
        task = task.strip()
    else:
        task = raw_arg.strip()
        roles = list(_DEFAULT_CREW)

    if not task or not roles:
        console.print("[err]usage: /subagent <task>  ·  /subagent role1,role2:<task>[/err]")
        return

    cwd = Path(session.cwd)
    parent_ctx, picks, why = _build_context(task, session=session, cwd=cwd, console=console)
    if picks:
        _ui.render_skills_picked(console, picks, why)

    specs = [
        SubAgentSpec(name=role, role=role, task=task)  # type: ignore[arg-type]
        for role in roles
    ]
    console.print(f"[brand]── parallel agents ({len(specs)}) ──[/brand]")

    # Live status table: spinner per role; flips to ✓ / ✗ on completion.
    statuses: dict[str, str] = {r: "running" for r in roles}

    def _render_table() -> Table:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="key")
        table.add_column()
        for r in roles:
            st = statuses[r]
            if st == "running":
                table.add_row(Spinner("dots", style="brand"), f"[brand]{r}[/brand]: working…")
            elif st == "ok":
                table.add_row("[ok]✓[/ok]", f"[brand]{r}[/brand]: done")
            else:
                table.add_row("[err]✗[/err]", f"[brand]{r}[/brand]: error")
        return table

    results: list[SubAgentResult] = []

    def _on_done(result: SubAgentResult) -> None:
        statuses[result.name] = "ok" if result.ok else "err"

    with Live(_render_table(), console=console, refresh_per_second=8, transient=False) as live:
        results = run_subagents_parallel(
            specs,
            parent_context=parent_ctx,
            project_cwd=cwd,
            parent_provider=session.provider,
            parent_model=session.model,
            max_concurrency=min(4, len(specs)),
            on_done=lambda r: (_on_done(r), live.update(_render_table())),
        )
        live.update(_render_table())

    # Per-result panel.
    for r in results:
        if r.ok:
            console.print(
                f"\n[brand]── {r.name}[/brand] [meta]({r.duration_seconds:.1f}s · "
                f"{r.usage.total_tokens:,} tok)[/meta]"
            )
            if r.plan:
                _ui.render_plan(console, r.plan, r.tradeoffs, r.verdict)
            if r.code:
                _ui.render_code(console, r.code)
            if r.defense:
                _ui.render_defense(console, r.defense)
        else:
            console.print(f"\n[err]✗ {r.name} failed:[/err] {r.error}")

    # Roll into the session as one turn.
    total_usage = aggregate_usage(results)
    turn = TaskTurn(
        task=f"/subagent {raw_arg}",
        plan="\n\n".join(f"### {r.name}\n{r.plan}" for r in results if r.plan),
        tradeoffs="\n\n".join(f"### {r.name}\n{r.tradeoffs}" for r in results if r.tradeoffs),
        verdict="\n".join(f"{r.name}: {r.verdict}" for r in results if r.verdict),
        code="\n\n".join(f"# from {r.name}\n{r.code}" for r in results if r.code),
        defense="\n\n".join(f"### {r.name}\n{r.defense}" for r in results if r.defense),
        usage=total_usage,
        cost_usd=sum(
            estimate_cost_usd(session.provider, session.model, r.usage) for r in results
        ),
        skills_used=picks,
    )
    session.record(turn)
    _ui.render_usage_line(
        console,
        label="parallel agents",
        usage_total=turn.usage.total_tokens,
        cost_usd=turn.cost_usd,
        budget_usd=session.budget_usd,
    )
    _ui.render_footer(console, session)


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
    cwd = Path(session.cwd)
    ctx, picks, why = _build_context(task, session=session, cwd=cwd, console=console)
    if picks:
        _ui.render_skills_picked(console, picks, why)

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
