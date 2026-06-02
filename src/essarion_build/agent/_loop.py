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
from .._windowing import head_tail_window
from ._session import (
    Session,
    TaskTurn,
    estimate_cost_usd,
)
from ._skill_picker import explain_pick, pick_skills
from . import _tools, _ui, _hooks
from ._commands import dispatch as dispatch_command


# Regex that finds path-shaped tokens in a user message. Used by the
# auto-attach step to load files the user clearly wants the agent to see.
_PATH_RE = re.compile(r"(?:\b|^)([\w/._-]+\.(?:py|ts|tsx|js|jsx|md|sql|toml|yml|yaml|json|rs|go|java|kt|rb|sh))(?:\b|$)")
# Inline `@path` references (Gemini / Claude-Code style): `@src/auth.py`, `@src/`.
# The lookbehind skips e-mail addresses (`user@host`) — the `@` must follow a
# non-word, non-`@` char. Lets a user steer exploration explicitly, including
# files whose extension `_PATH_RE` doesn't enumerate.
_AT_PATH_RE = re.compile(r"(?<![\w@])@([\w./-]+)")


def _related_paths(rel: str, cwd: Path) -> list[str]:
    """Given a source file path, guess where its test file lives (or vice versa).

    Common conventions handled:
    - `src/foo.py`     → `tests/test_foo.py`
    - `src/auth/login.py` → `tests/test_auth_login.py` / `tests/test_login.py`
    - `tests/test_foo.py` → `src/foo.py`
    - JS / TS: `src/foo.ts` ↔ `src/foo.test.ts` / `__tests__/foo.test.ts`

    Returns paths to *check* (relative to cwd); caller verifies existence.
    """
    from pathlib import PurePosixPath

    p = PurePosixPath(rel)
    stem = p.stem
    suffix = p.suffix
    parts = list(p.parts)
    candidates: list[str] = []

    # Python: src/foo/bar.py ↔ tests/test_bar.py (or tests/<dir>/test_bar.py)
    if suffix == ".py":
        if stem.startswith("test_"):
            # Test → source. Strip the test_ prefix and look in common src paths.
            src_stem = stem[len("test_") :]
            for src_root in ("src/essarion_build", "src", "lib", ""):
                for sub in (parts[1:-1] if len(parts) > 2 else [], []):
                    candidates.append(str(PurePosixPath(src_root, *sub, src_stem + ".py")).lstrip("/"))
            # Also try without the test_ prefix
            for src_root in ("src", "lib", ""):
                candidates.append(str(PurePosixPath(src_root, src_stem + ".py")).lstrip("/"))
        else:
            # Source → test. Try common test paths.
            candidates.append(f"tests/test_{stem}.py")
            candidates.append(f"tests/{stem}_test.py")
            if len(parts) > 1:
                # Reflect the source dir into a test dir
                middle = "_".join(parts[1:-1]) if len(parts) > 2 else ""
                if middle:
                    candidates.append(f"tests/test_{middle}_{stem}.py")
    # JS/TS: foo.ts ↔ foo.test.ts / foo.spec.ts ↔ __tests__/foo.test.ts
    if suffix in {".ts", ".tsx", ".js", ".jsx"}:
        if ".test" in stem or ".spec" in stem:
            src_stem = stem.replace(".test", "").replace(".spec", "")
            candidates.append(str(PurePosixPath(*parts[:-1], src_stem + suffix)).lstrip("/"))
        else:
            for ext in (".test", ".spec"):
                candidates.append(str(PurePosixPath(*parts[:-1], f"{stem}{ext}{suffix}")).lstrip("/"))
            if len(parts) > 1:
                candidates.append(str(PurePosixPath(*parts[:-1], "__tests__", f"{stem}.test{suffix}")).lstrip("/"))

    # Dedup, preserve order.
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out
# Directory references — words that look like "src/auth/" or "tests/".
_DIR_RE = re.compile(r"(?:\b|^)((?:[\w._-]+/)+)(?:\b|$|\s)")
# How many files to auto-attach from a referenced directory.
_DIR_AUTOLOAD_MAX = 8


# Directory names we never auto-attach files from.
_DIR_SKIP_PARTS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}


def _attach_one_file(
    rel: str, cwd: Path, ctx: Context, loaded: list[str], seen_paths: set[str],
    *, with_siblings: bool = True,
) -> bool:
    """Attach a single file (windowed) and, optionally, its sibling test file.

    Returns True if the file was attached. The sibling auto-load is the
    "review src/auth.py" → also load "tests/test_auth.py" trick that makes
    review and fix-bug workflows much smarter.
    """
    if rel in seen_paths:
        return False
    path = cwd / rel
    if not path.is_file():
        return False
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    ctx.repo_files.append(RepoFile(path=rel, content=head_tail_window(content, max_chars=200_000)))
    loaded.append(rel)
    seen_paths.add(rel)
    if with_siblings:
        for sibling in _related_paths(rel, cwd):
            if sibling in seen_paths:
                continue
            sp = cwd / sibling
            if not sp.is_file():
                continue
            try:
                sibling_content = sp.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            ctx.repo_files.append(
                RepoFile(path=sibling, content=head_tail_window(sibling_content, max_chars=100_000))
            )
            loaded.append(sibling)
            seen_paths.add(sibling)
    return True


def _attach_dir(rel: str, cwd: Path, ctx: Context, loaded: list[str], seen_paths: set[str]) -> None:
    """Attach the first `_DIR_AUTOLOAD_MAX` files from a referenced directory,
    skipping VCS/build dirs."""
    d = cwd / rel
    if not d.is_dir():
        return
    count_for_dir = 0
    for p in sorted(d.rglob("*")):
        if not p.is_file() or any(part in _DIR_SKIP_PARTS for part in p.parts):
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
        ctx.repo_files.append(RepoFile(path=rel_p, content=head_tail_window(content, max_chars=100_000)))
        loaded.append(rel_p)
        seen_paths.add(rel_p)
        count_for_dir += 1
        if count_for_dir >= _DIR_AUTOLOAD_MAX:
            break


def _autoload_files(task: str, cwd: Path, ctx: Context, console) -> list[str]:
    """If the user names any files or directories in their task, load them
    into the context.

    Three signals, highest first:
    - `@path` references (`@src/auth.py`, `@src/`) — an explicit, Gemini-style
      affordance that also works for files whose extension isn't enumerated.
    - bare path-shaped tokens (`src/auth.py`) attach individually (+ sibling tests).
    - directory references (`src/auth/`) attach up to `_DIR_AUTOLOAD_MAX` files.
    """
    loaded: list[str] = []
    seen_paths: set[str] = set()

    # 1. Explicit @path references first — the strongest "look at this" signal.
    for match in _AT_PATH_RE.finditer(task):
        rel = match.group(1).rstrip("/.,;:")
        if not rel:
            continue
        if (cwd / rel).is_dir():
            _attach_dir(rel, cwd, ctx, loaded, seen_paths)
        else:
            _attach_one_file(rel, cwd, ctx, loaded, seen_paths)

    # 2. Bare path-shaped tokens (src/auth.py) + their sibling tests.
    for match in _PATH_RE.finditer(task):
        _attach_one_file(match.group(1), cwd, ctx, loaded, seen_paths)

    # 3. Directory references — attach the first N files inside.
    for match in _DIR_RE.finditer(task):
        _attach_dir(match.group(1).rstrip("/"), cwd, ctx, loaded, seen_paths)

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
    # Multi-turn coherence: include the last 2 turns so the model picks up
    # decisions already made this session. Truncated for token budget.
    if session.history:
        recent = session.history[-2:]
        for i, prior in enumerate(recent, start=len(session.history) - len(recent) + 1):
            verdict_short = _truncate_one_line(prior.verdict, 200)
            plan_short = _truncate_one_line(prior.plan, 400)
            ctx.add_note(
                f"[prior turn {i}] task: {prior.task[:200]!r}. "
                f"Plan: {plan_short}. Verdict: {verdict_short}."
            )
    loaded = _autoload_files(task, cwd, ctx, console)
    # Cross-tool project conventions (AGENTS.md / CLAUDE.md / .cursorrules …) so
    # a repo set up for any agent steers this one too.
    try:
        from ._conventions import inject_into_context as _inject_conventions

        _inject_conventions(cwd, ctx)
    except Exception:  # noqa: BLE001 - conventions must never break a turn
        pass
    # Repo map — a ranked skeleton of the codebase (Aider-style) so the model
    # can orient without blind-grepping. Budgeted and biased toward whatever
    # files the task referenced.
    try:
        _inject_repo_map(cwd, ctx, focus=loaded)
    except Exception:  # noqa: BLE001 - repo map must never break a turn
        pass
    return ctx, picks, why


def _inject_repo_map(cwd: Path, ctx: Context, *, focus: list[str]) -> None:
    """Attach a token-budgeted repo map to the context. Off via the project's
    `[agent] repo_map = false`; size via `[agent] repo_map_chars`."""
    from ._project import find_project_root, load_project_config
    from ._repomap import build_index, render_map

    try:
        agent_cfg = load_project_config(find_project_root(cwd)).get("agent") or {}
    except Exception:  # noqa: BLE001
        agent_cfg = {}
    if agent_cfg.get("repo_map") is False:
        return
    budget = max(500, min(int(agent_cfg.get("repo_map_chars", 6000)), 20_000))
    text = render_map(build_index(cwd), focus=set(focus) or None, budget_chars=budget)
    if text:
        ctx.add_note(text)


def _truncate_one_line(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"


def _make_runtime(provider: str, model: str) -> LiteRuntime:
    """Build a fresh runtime each turn so the agent picks up /model swaps.

    Wraps the underlying builder so a missing API key becomes a typed,
    actionable error instead of a generic RuntimeError. This is the seam tests
    patch; cheap-triage de-escalation is layered on top in `_runtime_for`.
    """
    try:
        prov = build_provider(name=provider, api_key=None, model=model)
    except RuntimeError as e:
        # The SDK raises RuntimeError("OPENROUTER_API_KEY is not set ...")
        # — wrap so the agent path can surface a friendlier message.
        raise _MissingKeyError(str(e)) from e
    return LiteRuntime(prov)


def _attach_triage(runtime: Any, session: Session) -> None:
    """Point the runtime's triage call at the session's cheap model, if set.

    A no-op when no triage model is configured (or it equals the main model), or
    when the runtime doesn't expose a triage seam — so a stubbed/patched runtime
    in tests is left untouched. Triage is an optimization; failures fall back to
    the main model rather than breaking the turn.
    """
    tm = getattr(session, "triage_model", None)
    if not tm or tm == session.model or not hasattr(runtime, "_triage_provider"):
        return
    try:
        runtime._triage_provider = build_provider(
            name=session.provider, api_key=None, model=tm
        )
    except Exception:  # noqa: BLE001 - triage is an optimization, never fatal
        pass


def _runtime_for(session: Session, *, model: str | None = None) -> LiteRuntime:
    """The runtime for a reason()/generate() call: the main provider (via the
    `_make_runtime` seam) with the session's cheap triage model attached."""
    rt = _make_runtime(session.provider, model or session.model)
    _attach_triage(rt, session)
    return rt


class _MissingKeyError(RuntimeError):
    """Distinguishable from a network/HTTP RuntimeError. Caught and rendered
    by the phase runners with an actionable hint."""


def _looks_like_reject(verdict: str) -> bool:
    """Heuristic: did the selfcheck say "do not ship"?"""
    text = (verdict or "").lower()
    return "do not ship" in text or "not ship without" in text


def _run_plan_phase(
    console, session: Session, ctx: Context, task: str, turn: TaskTurn,
    *, quiet: bool = False,
) -> Reasoning | None:
    """Run reason() and (unless `quiet`) render the plan panel. Returns the
    Reasoning or None on err.

    `quiet=True` is used by the autonomous turn: the plan is still computed and
    fed to the executor, but nothing is rendered — planning happens internally,
    Claude-Code style, instead of showing a wall of plan/tradeoffs/verdict.

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

    if not quiet:
        _ui.render_phase_header(console, "plan")

    def _do_reason() -> Reasoning | None:
        with console.status(
            "[brand]thinking…[/brand] [hint](plan → selfcheck)[/hint]",
            spinner="line",
        ):
            try:
                return reason(
                    task,
                    context=ctx,
                    _runtime=_runtime_for(session),
                    max_tokens=session.max_tokens,
                    effort=session.effort,
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
        if not quiet:
            console.print(
                f"[meta]ran[/meta] [brand]{len(results)}[/brand] [meta]tool call(s) inline; "
                f"folded {n} result(s) into context, re-planning…[/meta]"
            )
        rounds += 1
        r = _do_reason()
        if r is None:
            return None
    _record_phase_usage(turn, session, r.usage)
    if getattr(r, "effort", ""):
        turn.effort = r.effort
        if not quiet and session.effort == "auto":
            console.print(
                f"[meta]reasoning depth: [/meta][phase.plan]{r.effort}[/phase.plan]"
                f"[meta] (auto-sized for this task)[/meta]"
            )
    if not quiet:
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
            spinner="line",
        ):
            try:
                g = generate(
                    task,
                    context=ctx,
                    _runtime=_runtime_for(session),
                    max_tokens=session.max_tokens,
                    effort=session.effort,
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
            spinner="line",
        ):
            try:
                g2 = generate(
                    task,
                    context=ctx,
                    _runtime=_runtime_for(session, model=session.escalate_model),
                    max_tokens=session.max_tokens,
                    effort=session.effort,
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
    runtime = _runtime_for(session)
    _ui.render_phase_header(console, "plan")
    try:
        with console.status("[brand]workflow…[/brand]", spinner="line"):
            if head == "review":
                r = workflows.review(body, context=ctx, _runtime=runtime, effort=session.effort)
            elif head == "security-review":
                r = workflows.security_review(body, context=ctx, _runtime=runtime, effort=session.effort)
            elif head == "perf-review":
                r = workflows.performance_review(body, context=ctx, _runtime=runtime, effort=session.effort)
            elif head == "explain":
                r = workflows.explain_code(body, context=ctx, _runtime=runtime, effort=session.effort)
            elif head == "fix-bug":
                g = workflows.fix_bug(body, context=ctx, _runtime=runtime, effort=session.effort)
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
                g = workflows.write_tests(body, context=ctx, _runtime=runtime, effort=session.effort)
                _record_phase_usage(turn, session, g.usage)
                turn.plan = g.reasoning.plan
                turn.code = g.code
                _ui.render_plan(console, g.reasoning.plan, g.reasoning.tradeoffs, g.reasoning.verdict)
                _ui.render_defense(console, g.defense)
                _apply_or_save(console, session, turn, g.code)
                return True
            elif head == "refactor":
                g = workflows.refactor(body, context=ctx, _runtime=runtime, effort=session.effort)
                _record_phase_usage(turn, session, g.usage)
                turn.plan = g.reasoning.plan
                turn.code = g.code
                _ui.render_plan(console, g.reasoning.plan, g.reasoning.tradeoffs, g.reasoning.verdict)
                _ui.render_defense(console, g.defense)
                _apply_or_save(console, session, turn, g.code)
                return True
            elif head == "docs":
                g = workflows.docs(body, context=ctx, _runtime=runtime, effort=session.effort)
                _record_phase_usage(turn, session, g.usage)
                turn.code = g.code
                _ui.render_plan(console, g.reasoning.plan, g.reasoning.tradeoffs, g.reasoning.verdict)
                _apply_or_save(console, session, turn, g.code)
                return True
            elif head == "pr-description":
                g = workflows.write_pr_description(body, context=ctx, _runtime=runtime, effort=session.effort)
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


def _suggest_next_actions(console, session: Session, turn: TaskTurn) -> None:
    """Print 2-3 suggested next slash commands based on what just happened.

    Order (most-important first):
    1. Budget warning if past 80% of cap
    2. /fix if the verdict said "do not ship"
    3. /diff /verify /commit if files were touched
    4. /undo if code was generated but discarded
    """
    suggestions: list[str] = []

    # 1. Budget nudge — always surface first when at risk.
    if session.budget_usd > 0 and session.total_cost_usd > session.budget_usd * 0.8:
        suggestions.append(
            "[key]/budget[/key] [meta]you're at 80% of budget[/meta]"
        )

    # 2. Verdict-driven follow-up.
    if turn.verdict and "do not ship" in turn.verdict.lower():
        suggestions.append(
            "[key]/fix <follow-up>[/key] [meta]address the blockers[/meta]"
        )

    # 3. Post-change suggestions.
    if turn.files_touched:
        suggestions.append("[key]/diff[/key] [meta]see the change[/meta]")
        suggestions.append("[key]/verify[/key] [meta]run tests/lint[/meta]")
        suggestions.append("[key]/commit[/key] [meta]git-commit[/meta]")
    elif turn.code:
        suggestions.append("[key]/undo[/key] [meta]revert[/meta]")

    if not suggestions:
        return
    console.print(
        "[hint]next:[/hint] " + "  ·  ".join(suggestions[:3])
    )


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
    from .. import approx_generate_calls
    from ._pricing import estimate_turn_cost_usd, format_cost

    if _hooks.fire("user_prompt", {"prompt": task}, console).blocked:
        console.print("[warn]task blocked by a user_prompt hook.[/warn]")
        return
    cwd = Path(session.cwd)
    ctx, picks, why = _build_context(task, session=session, cwd=cwd, console=console)
    if picks:
        _ui.render_skills_picked(console, picks, why)

    # Project the call count from the effort. For "auto" we can't know the
    # resolved depth until triage runs, so assume "deep" as a conservative
    # upper-ish bound (+1 for the triage call itself).
    if session.effort == "auto":
        n_calls = approx_generate_calls("deep") + 1
    else:
        try:
            n_calls = approx_generate_calls(session.effort)
        except Exception:  # noqa: BLE001
            n_calls = 3

    # Pre-flight projected cost so the user sees what this turn will cost
    # before paying for it.
    tokens, projected = estimate_turn_cost_usd(
        ctx, provider=session.provider, model=session.model,
        max_tokens=session.max_tokens, n_calls=n_calls,
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
                max_tokens=session.max_tokens, n_calls=n_calls,
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
            budget_usd=session.budget_usd, cached=turn.usage.cached_tokens,
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
            budget_usd=session.budget_usd, cached=turn.usage.cached_tokens,
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

    # 4.6 Suggested next actions.
    _suggest_next_actions(console, session, turn)

    # 5. Footer
    session.record(turn)
    _ui.render_usage_line(
        console,
        label="turn usage",
        usage_total=turn.usage.total_tokens,
        cost_usd=turn.cost_usd,
        budget_usd=session.budget_usd, cached=turn.usage.cached_tokens,
    )
    if session.total_cost_usd > session.budget_usd:
        console.print(
            f"[cost.over]budget exceeded by ${session.total_cost_usd - session.budget_usd:.4f}[/cost.over]"
        )
    _ui.render_footer(console, session)
    _hooks.fire("stop", {"task": task, "files_touched": turn.files_touched}, console)


def _classify_changes(entries) -> tuple[list[str], list[str], list[str]]:
    """Collapse a turn's change-log entries (per path) into the net
    (created, edited, deleted) path lists for the compact change summary."""
    first_before: dict[str, str | None] = {}
    last_kind: dict[str, str] = {}
    order: list[str] = []
    for e in entries:
        if e.path not in first_before:
            first_before[e.path] = e.before
            order.append(e.path)
        last_kind[e.path] = e.kind
    created: list[str] = []
    edited: list[str] = []
    deleted: list[str] = []
    for path in order:
        if last_kind[path] == "delete":
            deleted.append(path)
        elif first_before[path] is None:
            created.append(path)
        else:
            edited.append(path)
    return created, edited, deleted


def run_turn_autonomous(console, session: Session, task: str):
    """Plan internally, then build the whole task autonomously with real tools.

    This is the default, Claude-Code / Codex-style "agentic" turn. The agent
    sizes a quick internal plan (no approval prompt — planning happens
    internally, you just see it), then hands the goal to the agentic executor,
    which creates/edits/deletes files and runs commands directly on disk, in a
    loop, until the goal is done or a safety cap is hit. There is no "apply one
    file" step — every change lands immediately and is captured in the change
    log so `/undo` and `/diff` still work.

    Returns the executor's ExecResult (or None if it bailed before executing).
    For the classic plan → approve → hand-apply flow, use `/auto off` (which
    routes to `run_turn`).
    """
    from . import _agent_exec
    from ._changes import ChangeLog, current_changelog

    if _hooks.fire("user_prompt", {"prompt": task}, console).blocked:
        console.print("[warn]task blocked by a user_prompt hook.[/warn]")
        return
    cwd = Path(session.cwd)
    ctx, picks, why = _build_context(task, session=session, cwd=cwd, console=console)
    if picks:
        _ui.render_skills_picked(console, picks, why)

    turn = TaskTurn(task=task, skills_used=picks)

    # Workflow-prefixed shortcut ("review: …") still routes to workflows.
    if _maybe_handle_workflow(task, console, session, ctx, turn):
        session.record(turn)
        _ui.render_usage_line(
            console, label="turn usage", usage_total=turn.usage.total_tokens,
            cost_usd=turn.cost_usd, budget_usd=session.budget_usd, cached=turn.usage.cached_tokens,
        )
        _ui.render_footer(console, session)
        return

    # 1. PLAN phase — computed silently (quiet) and fed to the executor as
    #    context. No wall of plan/tradeoffs/verdict; planning is internal.
    r = _run_plan_phase(console, session, ctx, task, turn, quiet=True)
    if r is None:
        session.record(turn)
        return
    turn.plan = r.plan
    turn.tradeoffs = r.tradeoffs
    turn.verdict = r.verdict

    # 2. Budget check only — NO approval gate. Planning happened internally
    #    above; the agent now executes straight through, Claude-Code style. Use
    #    `/auto off` if you want the plan → approve → hand-apply checkpoint back.
    if not _check_budget(console, session, turn):
        session.record(turn)
        _ui.render_footer(console, session)
        return None

    # 3. AUTONOMOUS EXECUTION — real disk writes/edits/deletes + shell. The
    #    executor narrates and prints one compact line per action; no header
    #    needed (and Q&A turns shouldn't be labelled "build").
    log = current_changelog()
    start = len(log.entries)

    # Computer use (opt-in): extend the toolset with the browser_* and/or
    # desktop_* tools and launch backends for this turn. Never on by default.
    from . import _computer

    allow = set(_agent_exec.AUTONOMOUS_ALLOW)
    extra_parts: list[str] = []
    backend = None
    desktop_backend = None
    if _computer.computer_use_active(session, task):
        from ..computer import COMPUTER_TOOL_NAMES

        try:
            backend = _computer.start_computer_session(session)
            allow |= COMPUTER_TOOL_NAMES
            extra_parts.append(_computer.COMPUTER_PROTOCOL)
            console.print("[brand]🖥  computer use enabled[/brand] [meta](browser tools active)[/meta]")
        except Exception as e:  # noqa: BLE001 - surface, don't crash the turn
            console.print(f"[warn]computer use requested but the browser backend could not start:[/warn] {e}")
    elif _computer.suggests_desktop(task) and not _computer.desktop_active(session):
        console.print(
            "[hint]this looks like a desktop task. Desktop control is off by default "
            "(it drives your real machine) — enable it with [key]/desktop on[/key] or "
            "[key]--desktop[/key], then ask again.[/hint]"
        )
    if _computer.desktop_active(session):
        from ..computer import DESKTOP_TOOL_NAMES

        try:
            desktop_backend = _computer.start_desktop_session(session)
            allow |= DESKTOP_TOOL_NAMES
            extra_parts.append(_computer.DESKTOP_PROTOCOL)
            console.print("[err]🖥  DESKTOP CONTROL enabled[/err] [meta](real mouse/keyboard/screen)[/meta]")
        except Exception as e:  # noqa: BLE001
            console.print(f"[warn]desktop control requested but could not start:[/warn] {e}")

    # Permission policy from the project's .essarion/config.toml [permissions].
    from ._permissions import PermissionPolicy

    try:
        from ._project import find_project_root, load_project_config

        _perm_cfg = load_project_config(find_project_root(session.cwd)).get("permissions") or {}
    except Exception:  # noqa: BLE001 - never let config break a turn
        _perm_cfg = {}
    policy = PermissionPolicy.from_config(_perm_cfg)

    try:
        result = _agent_exec.execute(
            console, session, task, ctx,
            make_runtime=_make_runtime, turn=turn, plan=turn.plan,
            allow=allow, extra_system="\n\n".join(extra_parts), policy=policy,
        )
    finally:
        if backend is not None:
            _computer.stop_computer_session(backend)
        if desktop_backend is not None:
            _computer.stop_desktop_session(desktop_backend)
    for p in result.files_touched:
        if p not in turn.files_touched:
            turn.files_touched.append(p)
    # Remember what we did, for the next turn's conversation memory.
    if result.summary:
        turn.summary = result.summary
    if result.actions:
        turn.actions = result.actions
    if result.todos:
        turn.todos = result.todos

    # 4. Compact, collapsed summary of this turn's on-disk changes (created /
    #    edited / deleted counts + names). The full diff is one `/diff` away.
    new_entries = log.entries[start:]
    if new_entries:
        created, edited, deleted = _classify_changes(new_entries)
        _ui.render_change_summary(console, created, edited, deleted)

    # 5. Auto-verify + suggestions + footer.
    _maybe_auto_verify(console, session, turn)
    _suggest_next_actions(console, session, turn)
    session.record(turn)
    _ui.render_usage_line(
        console, label="turn usage", usage_total=turn.usage.total_tokens,
        cost_usd=turn.cost_usd, budget_usd=session.budget_usd, cached=turn.usage.cached_tokens,
    )
    if session.budget_usd and session.total_cost_usd > session.budget_usd:
        console.print(
            f"[cost.over]budget exceeded by ${session.total_cost_usd - session.budget_usd:.4f}[/cost.over]"
        )
    _ui.render_footer(console, session)
    _hooks.fire("stop", {"task": task, "files_touched": turn.files_touched}, console)
    return result


def run_goal(console, session: Session, goal: str, *, max_rounds: int = 6) -> None:
    """Work autonomously toward `goal` until it's DONE — no stopping to ask.

    The single autonomous turn already runs to <done> or a step cap; /goal adds
    one thing: if a round stops at the step cap without finishing, it continues
    automatically — up to `max_rounds` or until the budget runs out. So
    `/goal run all tests and fix failures` just works until accomplished. (Since
    autonomous turns no longer stop for approval, /goal is now mostly a
    convenience wrapper that loops past the per-turn step cap.)"""
    session.autonomous = True
    console.print(f"[brand]🎯 goal:[/brand] {goal}")
    console.print("[hint]working autonomously until done — no approval stops. Ctrl-C to halt.[/hint]")
    current = goal
    for rnd in range(1, max_rounds + 1):
        result = run_turn_autonomous(console, session, current)
        if result is None:
            return
        if result.stopped_reason == "done":
            console.print(f"[ok]🎯 goal accomplished in {rnd} round(s).[/ok]")
            return
        if result.stopped_reason in ("budget", "error"):
            console.print(f"[warn]🎯 stopped ({result.stopped_reason}) before the goal was complete.[/warn]")
            return
        if session.budget_usd and session.total_cost_usd >= session.budget_usd:
            console.print("[warn]🎯 budget reached before the goal was complete.[/warn]")
            return
        console.print(f"[meta]🎯 round {rnd} hit the step cap; continuing toward the goal…[/meta]")
        current = f"Continue working until this goal is fully accomplished, then emit <done>:\n{goal}"
    console.print(f"[warn]🎯 reached the {max_rounds}-round limit; goal may be incomplete.[/warn]")


def run_task(console, session: Session, task: str) -> None:
    """Dispatch a free-text task to the right loop for the session's mode.

    Autonomous (the default) → the agentic build loop: plan internally, then
    create/edit/delete files and run commands on disk until done, no approval.
    Plan-first (`/auto off`) → plan → approve → hand-apply one change.

    This is the single entry point the REPL, the one-shot CLI, and custom
    slash commands all funnel through, so the mode is honored everywhere.
    """
    if getattr(session, "autonomous", True):
        run_turn_autonomous(console, session, task)
    else:
        run_turn(console, session, task)


def repl(console, session: Session) -> None:
    """The main interactive loop."""
    _tools.bind_tools(session.cwd)
    _hooks.fire("session_start", {"session_id": session.id, "cwd": session.cwd}, console)
    while True:
        # Show any background-task completion notices first so the user
        # sees long-running commands finish between turns.
        _ui.drain_background_notices(console)
        try:
            line = _ui.prompt_input(console, session)
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
        # Not a slash command → treat as a task. Autonomous (the default) builds
        # the whole task end-to-end on disk in a loop; plan-first (`/auto off`)
        # uses the plan → approve → hand-apply flow.
        run_task(console, session, line)
