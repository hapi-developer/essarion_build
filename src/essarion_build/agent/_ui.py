"""Rich-based UI primitives for the agent REPL.

Kept thin — the loop owns the control flow; this module just renders.
Functions here take a `Console`, not a global singleton, so tests can
construct a Console(record=True) and assert on the rendered output.
"""

from __future__ import annotations

from typing import Iterable

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ._session import Session
from ._theme import BANNER, BANNER_COMPACT, ESSARION_THEME, TAGLINE, TIPS


def make_console() -> Console:
    """Create a Console wired to the Essarion theme."""
    return Console(theme=ESSARION_THEME, highlight=False)


def show_banner(
    console: Console,
    session: Session,
    skill_count: int,
    *,
    project=None,
) -> None:
    """The welcome screen — shown once at REPL start.

    `project` (optional) is an `agent._project.Project`; when present we
    label the cwd row with the marker that identified the project root.
    """
    # Big block wordmark, or a compact one on very narrow terminals.
    console.print(BANNER if console.width >= 46 else BANNER_COMPACT)
    console.print(TAGLINE)
    console.print()
    # "Tips for getting started" box (Gemini-style welcome).
    tips_body = Group(*[
        Text.from_markup(f"[brand.dim]{i}.[/brand.dim] {tip}")
        for i, tip in enumerate(TIPS, start=1)
    ])
    console.print(
        Panel(
            tips_body,
            title="[brand]Tips for getting started[/brand]",
            title_align="left",
            border_style="brand.dim",
            padding=(1, 2),
        )
    )
    console.print()
    table = Table.grid(padding=(0, 2))
    table.add_column(style="meta", justify="right")
    table.add_column()
    table.add_row("session", session.id)
    if project is not None and getattr(project, "detected_by", ""):
        table.add_row(
            "project",
            f"{session.cwd}  [hint](detected by {project.detected_by})[/hint]",
        )
    else:
        table.add_row("cwd", session.cwd)
    table.add_row("model", f"{session.provider}/[brand]{session.model}[/brand]")
    if session.escalate_model:
        table.add_row("escalate", f"{session.provider}/[brand]{session.escalate_model}[/brand]")
    table.add_row("budget", f"$0.000 / [brand]${session.budget_usd:.2f}[/brand]")
    table.add_row("skills", f"{skill_count} bundled, picker mode [brand]{session.skills_mode}[/brand]")
    _effort_blurb = {
        "auto": "auto — triage sizes each task",
        "quick": "quick — plan only",
        "standard": "standard — plan + self-check",
        "deep": "deep — plan + critique + revise",
        "max": "max — + alternative-plan + synthesis",
    }.get(session.effort, session.effort)
    table.add_row("reasoning", f"[brand]{_effort_blurb}[/brand]")
    if getattr(session, "autonomous", True):
        table.add_row(
            "mode",
            "[brand]autonomous[/brand] [hint](agentic: writes/edits/runs on disk "
            "until done — /auto off for plan-first)[/hint]",
        )
    else:
        table.add_row(
            "mode",
            "[brand]plan-first[/brand] [hint](plan → approve → hand-apply — "
            "/auto on for autonomous)[/hint]",
        )
    console.print(table)
    console.print()
    console.print(
        "[hint]type your task to begin · /help for commands · /bg <cmd> for background · /quit to exit[/hint]"
    )
    # First-run nudge: if we're not in an initialized project, suggest init.
    if project is not None and not getattr(project, "has_essarion_dir", False):
        console.print(
            "[hint]first time here? run `essarion init` to set up "
            ".essarion/{config.toml, sessions/, memory.md}.[/hint]"
        )
    console.print(Rule(style="brand.dim"))


def render_phase_header(console: Console, phase: str) -> None:
    """A small rule + label between phases."""
    label = {
        "plan": "[phase.plan]── plan ──[/phase.plan]",
        "draft": "[phase.draft]── draft ──[/phase.draft]",
        "build": "[phase.draft]── build ──[/phase.draft] [hint](autonomous — writing to disk)[/hint]",
        "selfcheck": "[phase.selfcheck]── selfcheck ──[/phase.selfcheck]",
    }.get(phase, phase)
    console.print(label)


def render_plan(console: Console, plan: str, tradeoffs: str, verdict: str) -> None:
    """The plan panel — what the user sees BEFORE any code is paid for."""
    body = Group(
        Text.from_markup("[phase.plan]plan[/phase.plan]"),
        Markdown(plan or "(no plan)"),
        Text(""),
        Text.from_markup("[phase.plan]tradeoffs[/phase.plan]"),
        Markdown(tradeoffs or "(no tradeoffs)"),
        Text(""),
        Text.from_markup("[phase.plan]verdict[/phase.plan]"),
        Markdown(verdict or "(no verdict)"),
    )
    console.print(Panel(body, border_style="brand", padding=(1, 2)))


def render_code(console: Console, code: str, *, language: str = "python") -> None:
    """Syntax-highlighted code block."""
    if not code.strip():
        console.print("[warn](no code produced)[/warn]")
        return
    console.print(
        Panel(
            Syntax(code, language, theme="ansi_dark", line_numbers=False),
            title=f"[phase.draft]code[/phase.draft]",
            border_style="phase.draft",
            padding=(0, 1),
        )
    )


def render_defense(console: Console, defense: str) -> None:
    if not defense.strip():
        return
    console.print(
        Panel(
            Markdown(defense),
            title="[phase.selfcheck]defense[/phase.selfcheck]",
            border_style="phase.selfcheck",
            padding=(0, 1),
        )
    )


def render_diff(console: Console, diff_text: str) -> None:
    """Render a unified diff with green/red coloring."""
    lines: list[Text] = []
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            lines.append(Text(line, style="meta"))
        elif line.startswith("+"):
            lines.append(Text(line, style="diff.add"))
        elif line.startswith("-"):
            lines.append(Text(line, style="diff.remove"))
        elif line.startswith("@@"):
            lines.append(Text(line, style="diff.hunk"))
        else:
            lines.append(Text(line))
    console.print(
        Panel(
            Group(*lines),
            title="[phase.draft]diff[/phase.draft]",
            border_style="phase.draft",
            padding=(0, 1),
        )
    )


def render_skills_picked(console: Console, picks: list[str], reason: str = "") -> None:
    """One-line summary of which skills the picker loaded."""
    if not picks:
        console.print("[meta]no skills loaded for this turn[/meta]")
        return
    skill_chips = " ".join(f"[skill]{p}[/skill]" for p in picks)
    console.print(f"[meta]skills:[/meta] {skill_chips}")
    if reason:
        console.print(f"[hint]why: {reason}[/hint]")


def render_tool_run(console: Console, tool: str, args: dict, result: str, ok: bool) -> None:
    """A small block for one tool invocation (read_file, grep, …)."""
    arg_repr = ", ".join(f"{k}={v!r}" for k, v in args.items())
    head = f"[brand]→[/brand] [key]{tool}[/key]([meta]{arg_repr}[/meta])"
    status = "[ok]✓[/ok]" if ok else "[err]✗[/err]"
    snippet = result if len(result) < 600 else result[:600] + "\n... (truncated)"
    console.print(f"{head} {status}")
    if snippet.strip():
        console.print(Panel(snippet, border_style="meta", padding=(0, 1)))


def render_usage_line(
    console: Console, *, label: str, usage_total: int, cost_usd: float, budget_usd: float
) -> None:
    """One-line summary at the end of a turn."""
    pct = min(100.0, (cost_usd / budget_usd * 100.0) if budget_usd > 0 else 0.0)
    style = "cost.under" if pct < 60 else ("cost.warn" if pct < 90 else "cost.over")
    console.print(
        f"[meta]{label}[/meta] [meta]{usage_total:,} tokens · "
        f"[/meta][{style}]${cost_usd:.4f}[/{style}]"
        f"[meta] of ${budget_usd:.2f}[/meta]"
    )


def render_footer(console: Console, session: Session) -> None:
    """A persistent-feeling status line printed at the end of each turn."""
    pct = session.budget_used_pct() * 100.0
    style = "cost.under" if pct < 60 else ("cost.warn" if pct < 90 else "cost.over")
    pieces: list[tuple[str, str]] = [
        ("model ", "meta"),
        (f"{session.provider}/{session.model}", "brand"),
        ("  ·  ", "meta"),
        ("budget ", "meta"),
        (f"${session.total_cost_usd:.4f}", style),
        (f" / ${session.budget_usd:.2f}", "meta"),
        ("  ·  ", "meta"),
        ("tokens ", "meta"),
        (f"{session.total_usage.total_tokens:,}", "brand"),
        ("  ·  ", "meta"),
        ("turns ", "meta"),
        (f"{len(session.history)}", "brand"),
    ]
    # Add a background-task indicator if any are running.
    try:
        from . import _background as bg

        running = bg.current_manager().running_count()
        if running:
            pieces.extend([
                ("  ·  ", "meta"),
                ("bg ", "meta"),
                (f"{running} running", "warn"),
            ])
    except Exception:  # noqa: BLE001 - footer never crashes
        pass
    console.print(Text.assemble(*pieces))
    console.print(Rule(style="brand.dim"))


def drain_background_notices(console: Console) -> None:
    """Print one inline notice per completed background task. Called at the
    top of each REPL prompt so the user sees finishes between turns."""
    try:
        from . import _background as bg

        notices = bg.current_manager().drain_notices()
    except Exception:  # noqa: BLE001
        return
    for task in notices:
        style = {
            "done": "ok", "failed": "err", "killed": "err", "running": "warn",
        }.get(task.status, "meta")
        line = (
            f"[meta][bg][/meta] [brand][{task.id}][/brand] "
            f"[key]{task.name[:50]}[/key] → [{style}]{task.status}[/{style}]"
        )
        if task.exit_code is not None:
            line += f" [meta](exit {task.exit_code}, {task.elapsed_seconds:.1f}s)[/meta]"
        console.print(line)


# ---------- prompts ----------

def prompt_input(console: Console, session: Session | None = None) -> str:
    """The user-input prompt at the top of each turn.

    Delegates to the Claude-Code-style input (prompt_toolkit when available,
    Rich prompt otherwise). A fresh line is read every turn, so multi-word
    tasks like "please code a website" are captured whole — no `--task`,
    no shell quoting, no "only the first word" parsing.
    """
    from ._input import read_prompt

    return read_prompt(console, session)


def prompt_approve_plan(console: Console) -> str:
    """After showing the plan, ask the user what to do. Returns one of:
    "approve", "edit", "skip", "cancel"."""
    raw = Prompt.ask(
        "[brand]approve plan?[/brand] [hint](Enter=approve, e=edit, s=skip-to-draft, c=cancel)[/hint]",
        choices=["", "e", "s", "c"],
        default="",
        show_choices=False,
        show_default=False,
        console=console,
    )
    return {"": "approve", "e": "edit", "s": "skip", "c": "cancel"}[raw]


def prompt_approve_apply(console: Console, *, kind: str = "code") -> str:
    """After showing the code/diff, ask whether to apply. Returns one of:
    "apply", "save", "discard"."""
    raw = Prompt.ask(
        f"[brand]apply {kind}?[/brand] [hint](a=apply-to-disk, s=save-as-file, Enter=discard)[/hint]",
        choices=["", "a", "s"],
        default="",
        show_choices=False,
        show_default=False,
        console=console,
    )
    return {"": "discard", "a": "apply", "s": "save"}[raw]


def prompt_text(console: Console, prompt: str, *, default: str = "") -> str:
    return Prompt.ask(prompt, default=default, console=console).strip()
