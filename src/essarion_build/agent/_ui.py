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
    if session.budget_usd and session.budget_usd > 0:
        table.add_row("budget", f"$0.000 / [brand]${session.budget_usd:.2f}[/brand]")
    else:
        table.add_row("cost", "[brand]$0.000[/brand] [hint](no cap — /budget to set one)[/hint]")
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
    """One compact, dim line naming the skills the picker loaded. The verbose
    per-skill 'why' is intentionally omitted — it was noise every turn. (`reason`
    is kept for signature compatibility.)"""
    if not picks:
        return
    skill_chips = " ".join(f"[skill]{p}[/skill]" for p in picks)
    console.print(f"[meta]skills[/meta] {skill_chips}")


def _ellipsize(text: str, limit: int) -> str:
    """One-line, collapsed-to-`limit` version of `text` (… if cut)."""
    one = " ".join((text or "").split())
    return one if len(one) <= limit else one[: limit - 1].rstrip() + "…"


# Secret kinds we strip from anything rendered to the terminal (and stored in
# memory) — keys/tokens/private keys, but NOT emails/cards (too noisy here).
_SECRET_KINDS = [
    "aws_access_key", "aws_secret_key", "anthropic_key", "openrouter_key",
    "openai_key", "github_pat", "github_app_token", "stripe_key", "slack_token",
    "google_api_key", "bearer_token", "private_key_block",
]


def redact_secrets(text: str) -> str:
    """Strip API keys / tokens / private keys from `text` (best-effort)."""
    if not text:
        return text
    try:
        from ..redact import redact_text

        return redact_text(text, kinds=_SECRET_KINDS)[0]
    except Exception:  # noqa: BLE001 - redaction must never break rendering
        return text


def _short_tail(text: str, *, max_lines: int = 8, max_chars: int = 600) -> str:
    """A short slice of the END of command output for the collapsed view — the
    exit status / pass-fail summary usually lives at the tail, not the head."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    clipped = lines[-max_lines:]
    out = "\n".join(clipped)
    if len(out) > max_chars:
        out = "…" + out[-max_chars:]
    if len(lines) > max_lines:
        out = "… " + out
    return out


def render_action(
    console: Console,
    *,
    verb: str,
    target: str = "",
    ok: bool = True,
    detail: str = "",
    diff: str = "",
    output: str = "",
) -> None:
    """One compact, faded line per agent action — Claude-Code style.

    e.g. ``✓ Created  index.html`` or ``✓ Ran  npm test``. A long target is
    ellipsized; `diff` renders a small colored diff (for edits); `output`
    renders a short dim tail (for commands); failures show the error inline.
    """
    mark = "[ok]✓[/ok]" if ok else "[err]✗[/err]"
    tgt = _ellipsize(redact_secrets(target), 72)
    line = f"{mark} [meta]{verb}[/meta]"
    if tgt:
        line += f"  [hint]{tgt}[/hint]"
    if detail:
        line += f" [hint]{detail}[/hint]"
    console.print(line)
    if diff.strip():
        for ln in redact_secrets(diff).splitlines():
            if ln.startswith("+"):
                console.print(f"  [diff.add]{ln}[/diff.add]")
            elif ln.startswith("-"):
                console.print(f"  [diff.remove]{ln}[/diff.remove]")
            else:
                console.print(f"  [hint]{ln}[/hint]")
    tail = _short_tail(redact_secrets(output))
    if tail:
        style = "err" if not ok else "hint"
        for ln in tail.splitlines():
            console.print(f"  [{style}]{_ellipsize(ln, 100)}[/{style}]")


def render_change_summary(
    console: Console, created: list[str], edited: list[str], deleted: list[str]
) -> None:
    """A one/two-line collapsed summary of a turn's on-disk changes, instead of
    dumping the full diff. `/diff` shows the detail."""
    if not (created or edited or deleted):
        return
    parts: list[str] = []
    if created:
        parts.append(f"[diff.add]{len(created)} created[/diff.add]")
    if edited:
        parts.append(f"[diff.hunk]{len(edited)} edited[/diff.hunk]")
    if deleted:
        parts.append(f"[diff.remove]{len(deleted)} deleted[/diff.remove]")
    names = ", ".join((created + edited + deleted)[:8])
    extra = len(created) + len(edited) + len(deleted) - 8
    if extra > 0:
        names += f", +{extra} more"
    console.print(
        f"[meta]changes:[/meta] " + " · ".join(parts)
        + f"  [hint]{names}[/hint]  [hint]· /diff to view[/hint]"
    )


def render_usage_line(
    console: Console, *, label: str, usage_total: int, cost_usd: float,
    budget_usd: float, cached: int = 0,
) -> None:
    """One-line usage summary at the end of a turn: tokens (+ cache hits) + cost.
    The ' / budget' suffix only appears when a cap is set (otherwise we meter)."""
    cached_str = f" ({cached:,} cached)" if cached and cached > 0 else ""
    if budget_usd and budget_usd > 0:
        pct = min(100.0, cost_usd / budget_usd * 100.0)
        style = "cost.under" if pct < 60 else ("cost.warn" if pct < 90 else "cost.over")
        console.print(
            f"[meta]{label}[/meta] [meta]{usage_total:,} tokens{cached_str} · "
            f"[/meta][{style}]${cost_usd:.4f}[/{style}]"
            f"[meta] of ${budget_usd:.2f}[/meta]"
        )
    else:
        console.print(
            f"[meta]{label}[/meta] [meta]{usage_total:,} tokens{cached_str} · "
            f"[/meta][cost.under]${cost_usd:.4f}[/cost.under]"
        )


def render_footer(console: Console, session: Session) -> None:
    """A persistent-feeling status line printed at the end of each turn."""
    pct = session.budget_used_pct() * 100.0
    style = "cost.under" if pct < 60 else ("cost.warn" if pct < 90 else "cost.over")
    pieces: list[tuple[str, str]] = [
        ("model ", "meta"),
        (f"{session.provider}/{session.model}", "brand"),
        ("  ·  ", "meta"),
    ]
    if session.budget_usd and session.budget_usd > 0:
        pieces += [
            ("cost ", "meta"),
            (f"${session.total_cost_usd:.4f}", style),
            (f" / ${session.budget_usd:.2f}", "meta"),
        ]
    else:
        pieces += [
            ("cost ", "meta"),
            (f"${session.total_cost_usd:.4f}", "cost.under"),
        ]
    pieces += [
        ("  ·  ", "meta"),
        ("tokens ", "meta"),
        (f"{session.total_usage.total_tokens:,}", "brand"),
    ]
    if session.total_usage.cached_tokens > 0:
        pieces += [(f" ({session.total_usage.cached_tokens:,} cached)", "meta")]
    pieces += [
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


# ---------- ask_user (interactive multiple-choice, Claude-Code style) ----------

def _normalize_questions(spec: dict) -> list[dict]:
    """Coerce the ask_user tool args into a list of question dicts. Accepts a
    `questions` array or a single `question`/`options` pair."""
    if not isinstance(spec, dict):
        return []
    raw = spec.get("questions")
    if isinstance(raw, list):
        return [q for q in raw if isinstance(q, dict) and str(q.get("question", "")).strip()]
    if str(spec.get("question", "")).strip():
        return [spec]
    return []


def _resolve_choice(raw: str, options: list[str], other_n: int, read, console: Console) -> str:
    """Map the user's raw input to an answer: a number selects an option, the
    'Other' number (or any free text) becomes a typed answer."""
    raw = (raw or "").strip()
    if not raw:
        return options[0] if options else "(no answer)"
    if raw.isdigit():
        n = int(raw)
        if 1 <= n <= len(options):
            return options[n - 1]
        if n == other_n:
            try:
                custom = str(read("[brand]your answer:[/brand] ")).strip()
            except (EOFError, KeyboardInterrupt):
                custom = ""
            return custom or "(no answer)"
        return raw  # out-of-range number → treat literally
    return raw  # non-numeric → a free-text answer


def ask_user_questions(console: Console, spec: dict, *, input_fn=None) -> str:
    """Ask the user one or more multiple-choice questions mid-task and return the
    answers as text to feed back to the model (Claude-Code's AskUserQuestion).

    Each question shows up to 4 options plus an auto-added "Other (type your
    own)". The user answers by number, or by typing their own text. In a
    non-interactive context (no TTY and no injected `input_fn`) we never block —
    we tell the model to proceed with sensible defaults.
    """
    import sys

    questions = _normalize_questions(spec)
    if not questions:
        return "(ask_user was called with no questions; continue using your best judgment.)"

    interactive = input_fn is not None or (
        getattr(sys.stdin, "isatty", lambda: False)()
        and getattr(sys.stdout, "isatty", lambda: False)()
    )
    if not interactive:
        return (
            "(No interactive user is available to answer right now. Proceed with "
            "sensible defaults and note any assumptions you made.)"
        )

    read = input_fn or (lambda prompt: console.input(prompt))
    answers: list[str] = []
    for q in questions[:6]:
        text = str(q.get("question", "")).strip()
        header = str(q.get("header", "")).strip()
        options = [str(o) for o in (q.get("options") or [])][:4]
        label = f"[brand]?[/brand] [b]{text}[/b]"
        if header:
            label += f"  [hint]({header})[/hint]"
        console.print(label)
        for i, opt in enumerate(options, start=1):
            console.print(f"  [key]{i}[/key]. {opt}")
        other_n = len(options) + 1
        console.print(f"  [key]{other_n}[/key]. [hint]Other (type your own)[/hint]")
        try:
            raw = str(read(f"[brand]choose 1-{other_n} (or type an answer):[/brand] "))
        except (EOFError, KeyboardInterrupt):
            raw = ""
        answer = _resolve_choice(raw, options, other_n, read, console)
        answers.append(f"Q: {text}\nA: {answer}")
        console.print(f"  [ok]→ {answer}[/ok]")
    return "\n\n".join(answers)


def confirm_action(console: Console, verb: str, target: str, reason: str = "", *, input_fn=None) -> bool:
    """Ask the user to approve a guarded action (permission policy 'ask').
    Returns True to allow. Non-interactive (no TTY, no input_fn) → False (deny)."""
    import sys

    interactive = input_fn is not None or (
        getattr(sys.stdin, "isatty", lambda: False)()
        and getattr(sys.stdout, "isatty", lambda: False)()
    )
    tgt = _ellipsize(redact_secrets(target), 80)
    console.print(
        f"[warn]⚠ permission:[/warn] [meta]{verb}[/meta] [hint]{tgt}[/hint]"
        + (f"  [hint]({reason})[/hint]" if reason else "")
    )
    if not interactive:
        console.print("[hint]  no interactive user — denying (run with /yolo to auto-allow).[/hint]")
        return False
    read = input_fn or (lambda prompt: console.input(prompt))
    try:
        raw = str(read("[brand]  allow this? (y/N):[/brand] ")).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return raw in {"y", "yes"}


# ---------- live todo list (the agent's running checklist) ----------

_TODO_GLYPH = {"done": "[ok]☑[/ok]", "doing": "[brand]▶[/brand]", "todo": "[hint]☐[/hint]"}


def render_todos(console: Console, todos: list[dict]) -> None:
    """Render the agent's task checklist — one line per item with a state glyph,
    Claude-Code style, so a long autonomous task stays legible."""
    if not todos:
        return
    console.print("[meta]todo[/meta]")
    for item in todos:
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        status = str(item.get("status", "todo")).lower()
        glyph = _TODO_GLYPH.get(status, _TODO_GLYPH["todo"])
        style = "meta" if status == "done" else ("brand" if status == "doing" else "hint")
        console.print(f"  {glyph} [{style}]{_ellipsize(text, 84)}[/{style}]")
