"""Slash-command handlers for the agent REPL.

Every command is a function that takes (console, session, args_str) and
returns one of:

- `"continue"` — handled the command, prompt for the next user message.
- `"quit"`     — exit the REPL.

Adding a new command: write a function `_cmd_<name>`, add it to
`COMMANDS`. The dispatcher does the rest.
"""

from __future__ import annotations

import json
from typing import Callable

from rich.console import Console
from rich.table import Table

from .. import list_skills as _all_skills, list_providers
from . import _session, _tools, _ui
from ._session import Session

CommandResult = str  # "continue" | "quit"


# Which environment variable(s) hold each provider's API key. Empty tuple → the
# provider needs no key (local Ollama, the in-memory stub). Used to validate a
# `/model` switch and to render `/keys`.
_PROVIDER_ENVS: dict[str, tuple[str, ...]] = {
    "openrouter": ("OPENROUTER_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "ollama": (),
    "stub": (),
}


def _warn_if_key_missing(console: Console, provider: str) -> None:
    """Warn (don't block) when the just-selected provider's key isn't in the env.

    Switching from `openrouter` to `openai/...` silently needs a *different* key;
    surfacing which one up front beats a cryptic auth failure on the next task."""
    import os

    envs = _PROVIDER_ENVS.get(provider)
    if not envs:  # no key needed, or a custom provider we can't advise on
        return
    if any(os.environ.get(e) for e in envs):
        return
    console.print(
        f"[warn]heads up:[/warn] [brand]{provider}[/brand] needs [key]{envs[0]}[/key], "
        "which isn't set here. Export it — or add it to a .env file and run "
        "[key]/reload[/key] — before your next task."
    )


_HELP_GROUPS: list[tuple[str, list[str]]] = [
    ("session", ["/whoami", "/history", "/summary", "/save", "/load", "/export", "/clear", "/version", "/quit"]),
    ("autonomy", ["/goal"]),
    ("planning", ["/ask"]),
    ("workflows", ["/workflows", "/review", "/fix", "/tests", "/refactor", "/docs", "/security", "/perf", "/explain", "/pr"]),
    ("reasoning", ["/effort"]),
    ("models & cost", ["/model", "/escalate", "/triage", "/crosscheck", "/budget", "/cost", "/stream", "/keys", "/reload"]),
    ("skills & memory", ["/skills", "/remember", "/forget"]),
    ("project & files", ["/cd", "/pwd"]),
    ("code intelligence", ["/map", "/outline", "/symbol"]),
    ("changes & verify", ["/diff", "/undo", "/commit", "/verify", "/lint"]),
    ("background", ["/bg"]),
    ("safety", ["/auto", "/computer", "/desktop", "/yolo", "/hooks"]),
    ("help", ["/help"]),
]


def _cmd_help(console: Console, session: Session, args: str) -> CommandResult:
    """Show every slash command, grouped by area.

    `/help <substring>` filters to commands matching the substring.
    """
    arg = args.strip().lower()
    if arg and not arg.startswith("/"):
        arg = "/" + arg

    table = Table(title="essarion build · commands", title_style="brand", show_lines=False)
    table.add_column("group", style="phase.plan")
    table.add_column("command", style="key")
    table.add_column("description", style="meta")

    shown = 0
    seen: set[str] = set()
    for group, cmds in _HELP_GROUPS:
        for cmd in cmds:
            if cmd not in COMMANDS:
                continue
            seen.add(cmd)
            if arg and arg not in cmd:
                continue
            _, desc = COMMANDS[cmd]
            table.add_row(group, cmd, desc)
            shown += 1
        # blank row between groups for visual rhythm.
        if shown and not arg:
            table.add_row("", "", "")
    # Any commands not in _HELP_GROUPS (forgot to categorize) go in "misc".
    misc = [c for c in COMMANDS if c not in seen]
    if misc and not arg:
        for cmd in misc:
            _, desc = COMMANDS[cmd]
            table.add_row("misc", cmd, desc)

    console.print(table)
    if not arg:
        console.print(
            "[hint]anything not starting with `/` is treated as a task. "
            "`<verb>: <target>` (e.g. `review: src/auth.py`) routes to a workflow.[/hint]"
        )
    return "continue"


def _cmd_quit(console: Console, session: Session, args: str) -> CommandResult:
    return "quit"


def _cmd_clear(console: Console, session: Session, args: str) -> CommandResult:
    console.clear()
    return "continue"


def _set_budget(console: Console, session: Session, raw: str) -> bool:
    """Parse `raw` as a USD cap and apply it. 'off'/'none'/'0' clears the cap.
    Returns True if it parsed (and was applied), False if it wasn't a number."""
    arg = raw.strip().lstrip("$").lower()
    if arg in {"off", "none", "clear"}:
        session.budget_usd = 0.0
        console.print("[ok]budget cap removed — metering cost only.[/ok]")
        return True
    try:
        session.budget_usd = max(0.0, float(arg))
    except ValueError:
        return False
    if session.budget_usd > 0:
        console.print(f"[ok]budget cap set to ${session.budget_usd:.2f}[/ok]")
    else:
        console.print("[ok]budget cap removed — metering cost only.[/ok]")
    return True


def _cmd_budget(console: Console, session: Session, args: str) -> CommandResult:
    """Show spend, or set a spending cap. No cap by default — `/budget` with no
    argument shows the cost so far and (interactively) prompts for a cap."""
    if args.strip():
        if not _set_budget(console, session, args):
            console.print("[err]usage: /budget [amount-in-usd | off][/err]")
        return "continue"
    # No argument: show current spend.
    if session.budget_usd and session.budget_usd > 0:
        pct = session.budget_used_pct() * 100.0
        style = "cost.under" if pct < 60 else ("cost.warn" if pct < 90 else "cost.over")
        console.print(
            f"[meta]spent[/meta] [{style}]${session.total_cost_usd:.4f}[/{style}]"
            f"[meta] / ${session.budget_usd:.2f}  ({pct:.1f}%)[/meta]"
        )
    else:
        console.print(
            f"[meta]spent[/meta] [cost.under]${session.total_cost_usd:.4f}[/cost.under]"
            f"[meta]  (no cap set)[/meta]"
        )
    # Then prompt for a cap — but only when interactive, so pipes/tests/CI don't
    # block waiting on stdin.
    import sys

    if getattr(sys.stdin, "isatty", lambda: False)() and getattr(sys.stdout, "isatty", lambda: False)():
        entered = _ui.prompt_text(
            console, "[brand]set a budget cap in USD (blank = leave as-is)[/brand]"
        )
        if entered.strip():
            if not _set_budget(console, session, entered):
                console.print("[warn]not a number — budget unchanged.[/warn]")
    return "continue"


def _cmd_model(console: Console, session: Session, args: str) -> CommandResult:
    args = args.strip()
    if not args:
        console.print(
            f"[meta]current:[/meta] [brand]{session.provider}/{session.model}[/brand]"
            + (f"  [meta](escalate to {session.escalate_model})[/meta]"
               if session.escalate_model else "")
            + (f"  [meta](triage on {session.triage_model})[/meta]"
               if session.triage_model else "")
            + (f"  [meta](2nd opinion: {session.crosscheck_model})[/meta]"
               if session.crosscheck_model else "")
        )
        console.print(
            f"[hint]usage: /model <provider>/<model>  e.g. /model openai/gpt-4o-mini[/hint]"
        )
        return "continue"
    if "/" in args:
        provider, model = args.split("/", 1)
    else:
        provider, model = session.provider, args
    if provider not in list_providers():
        console.print(
            f"[err]unknown provider {provider!r}. known: {', '.join(list_providers())}[/err]"
        )
        return "continue"
    session.provider = provider
    session.model = model
    console.print(f"[ok]model set to {provider}/{model}[/ok]")
    _warn_if_key_missing(console, provider)
    return "continue"


def _cmd_triage(console: Console, session: Session, args: str) -> CommandResult:
    """Show or set the cheap triage model — the throwaway 'how hard is this task?'
    routing call made only when effort='auto'. De-escalating it to a pennies
    model keeps a capable default for the real reasoning at near-zero routing cost.

    Usage:
      /triage                 show the current triage model
      /triage <model>         route the auto triage call through <model>
      /triage off             run triage on the main model
    """
    args = args.strip()
    if not args:
        if session.triage_model:
            console.print(
                f"[meta]triage model:[/meta] [brand]{session.triage_model}[/brand] "
                "[meta](used only for effort=auto routing)[/meta]"
            )
        else:
            console.print("[meta]no triage model set — routing runs on the main model[/meta]")
        console.print("[hint]usage: /triage <model>  ·  /triage off[/hint]")
        return "continue"
    if args.lower() in {"off", "none", "clear"}:
        session.triage_model = None
        console.print("[ok]triage de-escalation off — routing uses the main model[/ok]")
        return "continue"
    session.triage_model = args
    console.print(
        f"[ok]auto-triage routing → {args}[/ok] "
        f"[meta](real reasoning stays on {session.model})[/meta]"
    )
    return "continue"


def _cmd_escalate(console: Console, session: Session, args: str) -> CommandResult:
    args = args.strip()
    if not args:
        if session.escalate_model:
            console.print(
                f"[meta]escalate model:[/meta] [brand]{session.escalate_model}[/brand]"
            )
        else:
            console.print("[meta]no escalate model set[/meta]")
        console.print(
            "[hint]usage: /escalate <model>  · used when selfcheck rejects[/hint]"
        )
        return "continue"
    if args.lower() in {"off", "none", "clear"}:
        session.escalate_model = None
        console.print("[ok]escalation disabled[/ok]")
        return "continue"
    session.escalate_model = args
    console.print(f"[ok]will escalate to {args} on selfcheck reject[/ok]")
    return "continue"


def _cmd_crosscheck(console: Console, session: Session, args: str) -> CommandResult:
    """Show or set the cross-model SECOND OPINION reviewer.

    A DIFFERENT model (ideally a different family, running on your current
    provider) independently red-teams every change — handed only the goal and
    the diff, so it's cheap. Where the two models disagree is where bugs hide.
    This is the cheap-ensemble idea: two pennies models catch what one misses.

    Usage:
      /crosscheck                 show the current reviewer
      /crosscheck <model>         review every change with <model>
      /crosscheck off             disable
    """
    args = args.strip()
    if not args:
        if session.crosscheck_model:
            console.print(
                f"[meta]second-opinion model:[/meta] [brand]{session.crosscheck_model}[/brand] "
                "[meta](independently reviews every change)[/meta]"
            )
        else:
            console.print("[meta]no second-opinion model set — changes aren't cross-checked[/meta]")
        console.print(
            "[hint]usage: /crosscheck <model>  ·  /crosscheck off  ·  "
            "best with a different model FAMILY[/hint]"
        )
        return "continue"
    if args.lower() in {"off", "none", "clear"}:
        session.crosscheck_model = None
        console.print("[ok]second opinion off[/ok]")
        return "continue"
    session.crosscheck_model = args
    console.print(f"[ok]second opinion on[/ok] [meta]— every change reviewed by {args}[/meta]")
    if args == session.model:
        console.print(
            "[warn]tip:[/warn] that's the same model that writes the change — a "
            "different family catches more (different blind spots)."
        )
    _warn_if_key_missing(console, session.provider)
    return "continue"


def _cmd_skills(console: Console, session: Session, args: str) -> CommandResult:
    args = args.strip().lower()
    if args in {"auto", "all", "none"}:
        session.skills_mode = args
        console.print(f"[ok]skills mode set to {args}[/ok]")
        return "continue"
    skills = _all_skills()
    console.print(
        f"[meta]{len(skills)} bundled skills · current mode: [/meta]"
        f"[brand]{session.skills_mode}[/brand]"
    )
    console.print("[hint]usage: /skills [auto|all|none][/hint]")
    cols = []
    for i, name in enumerate(skills):
        cols.append(f"[skill]{name}[/skill]")
        if (i + 1) % 4 == 0:
            console.print("  ".join(cols))
            cols = []
    if cols:
        console.print("  ".join(cols))
    return "continue"


def _cmd_cd(console: Console, session: Session, args: str) -> CommandResult:
    from pathlib import Path

    target = Path(args.strip() or ".").expanduser().resolve()
    if not target.is_dir():
        console.print(f"[err]not a directory: {target}[/err]")
        return "continue"
    session.cwd = str(target)
    _tools.bind_tools(target)
    console.print(f"[ok]cwd → {target}[/ok]")
    return "continue"


def _cmd_pwd(console: Console, session: Session, args: str) -> CommandResult:
    console.print(session.cwd)
    return "continue"


def _cmd_map(console: Console, session: Session, args: str) -> CommandResult:
    """Show the repo map — the ranked skeleton the agent sees each turn.
    Optional args bias the ranking toward those paths: /map src/auth.py"""
    from ._repomap import build_index, render_map

    focus = {a.strip() for a in args.split() if a.strip()} or None
    text = render_map(build_index(session.cwd), focus=focus, budget_chars=8000)
    console.print(text or "[meta]no indexable source files found[/meta]")
    return "continue"


def _cmd_outline(console: Console, session: Session, args: str) -> CommandResult:
    """Show one file's symbols + signatures: /outline path/to/file.py"""
    rel = args.strip()
    if not rel:
        console.print("[warn]usage:[/warn] /outline <file>")
        return "continue"
    from ._repomap import outline_text

    console.print(outline_text(session.cwd, rel))
    return "continue"


def _cmd_symbol(console: Console, session: Session, args: str) -> CommandResult:
    """Find where a symbol is defined and referenced: /symbol parse_config"""
    name = args.strip()
    if not name:
        console.print("[warn]usage:[/warn] /symbol <name>")
        return "continue"
    from ._repomap import find_symbol_text

    console.print(find_symbol_text(session.cwd, name))
    return "continue"


def _cmd_history(console: Console, session: Session, args: str) -> CommandResult:
    if not session.history:
        console.print("[meta]no turns yet[/meta]")
        return "continue"
    for i, turn in enumerate(session.history, 1):
        verdict_short = (turn.verdict or "").split("\n", 1)[0][:70]
        console.print(
            f"[meta]{i:>2}[/meta] [you]{turn.task[:60]}[/you]  "
            f"[meta]{turn.usage.total_tokens:>5,}t · ${turn.cost_usd:.4f}[/meta]"
            + (f"  [phase.selfcheck]{verdict_short}[/phase.selfcheck]" if verdict_short else "")
        )
    return "continue"


def _resolve_sessions_dir(session: Session):
    """Use the per-project sessions dir if the session's cwd lives inside a
    project; otherwise None (the helpers fall back to ~/.essarion/sessions/)."""
    from ._project import find_project_root

    project = find_project_root(session.cwd)
    return project.sessions_dir if project.has_essarion_dir else None


def _cmd_save(console: Console, session: Session, args: str) -> CommandResult:
    sd = _resolve_sessions_dir(session)
    path = _session.save_session(session, sessions_dir=sd)
    console.print(f"[ok]saved → {path}[/ok]")
    return "continue"


def _cmd_load(console: Console, session: Session, args: str) -> CommandResult:
    """Load is implemented at session-bootstrap time; here we just print sessions."""
    sd = _resolve_sessions_dir(session)
    sessions = _session.list_sessions(sessions_dir=sd)
    if not sessions:
        console.print("[meta]no saved sessions[/meta]")
        return "continue"
    table = Table(title="saved sessions", title_style="brand")
    table.add_column("id", style="key")
    table.add_column("model", style="meta")
    table.add_column("turns", justify="right")
    table.add_column("cost", justify="right")
    for s in sessions[-20:]:
        table.add_row(
            s.get("id", ""),
            s.get("model", ""),
            str(s.get("turns", 0)),
            f"${(s.get('cost_usd') or 0):.4f}",
        )
    console.print(table)
    console.print(
        "[hint]launch with `essarion --resume <id>` to continue a session.[/hint]"
    )
    return "continue"


def _cmd_export(console: Console, session: Session, args: str) -> CommandResult:
    """Dump the session as JSON to stdout for piping."""
    print(session.model_dump_json(indent=2))
    return "continue"


def _cmd_yolo(console: Console, session: Session, args: str) -> CommandResult:
    """Toggle auto-approval of side-effect tools."""
    from . import _tools as t

    current = getattr(t, "_AUTO_APPROVE", False)
    t._AUTO_APPROVE = not current
    new = "ON" if t._AUTO_APPROVE else "OFF"
    style = "warn" if t._AUTO_APPROVE else "meta"
    console.print(f"[{style}]auto-approve side-effects: {new}[/{style}]")
    return "continue"


def _cmd_version(console: Console, session: Session, args: str) -> CommandResult:
    from .. import __version__

    console.print(f"essarion-build [brand]{__version__}[/brand]")
    return "continue"


def _cmd_remember(console: Console, session: Session, args: str) -> CommandResult:
    from ._memory import load_memory

    memory = load_memory(session.cwd)
    arg = args.strip()
    if not arg:
        # Print current memory.
        if not memory.facts:
            console.print("[meta](no remembered facts)[/meta]")
            console.print(f"[hint]usage: /remember <fact>  ·  file: {memory.path}[/hint]")
            return "continue"
        from rich.panel import Panel

        body = "\n".join(f"- {f}" for f in memory.facts)
        console.print(
            Panel(body, title="[brand]project memory[/brand]", border_style="brand", padding=(0, 1))
        )
        console.print(f"[hint]{memory.path}[/hint]")
        return "continue"
    try:
        memory.add_fact(arg)
    except ValueError as e:
        console.print(f"[err]{e}[/err]")
        return "continue"
    memory.save()
    console.print(f"[ok]remembered[/ok] [meta]({len(memory.facts)} fact(s) total)[/meta]")
    return "continue"


def _cmd_forget(console: Console, session: Session, args: str) -> CommandResult:
    from ._memory import load_memory

    memory = load_memory(session.cwd)
    arg = args.strip()
    if not arg:
        console.print("[err]usage: /forget <pattern>  ·  /forget all[/err]")
        return "continue"
    if arg.lower() == "all":
        n = len(memory.facts)
        memory.clear()
        memory.save()
        console.print(f"[ok]forgot all {n} fact(s)[/ok]")
        return "continue"
    removed = memory.forget(arg)
    memory.save()
    if removed:
        console.print(f"[ok]removed {removed} fact(s) matching {arg!r}[/ok]")
    else:
        console.print(f"[meta]no facts matched {arg!r}[/meta]")
    return "continue"


def _cmd_verify(console: Console, session: Session, args: str) -> CommandResult:
    from ._verify import configured_check, run_check

    cmd, _auto = configured_check(session.cwd)
    target = args.strip() or cmd
    if not target:
        console.print(
            "[err]no verify command — set [verify].check_cmd in "
            ".essarion/config.toml or pass one: /verify pytest -q[/err]"
        )
        return "continue"
    console.print(f"[meta]running:[/meta] [key]{target}[/key]")
    with console.status("[brand]verifying…[/brand]"):
        result = run_check(target, cwd=session.cwd)
    style = "ok" if result.ok else "err"
    console.print(
        f"[{style}]{'PASS' if result.ok else 'FAIL'}[/{style}] "
        f"[meta]exit={result.exit_code}[/meta]"
    )
    if result.head.strip():
        from rich.panel import Panel

        console.print(Panel(result.head, border_style=style, padding=(0, 1)))
    return "continue"


def _cmd_lint(console: Console, session: Session, args: str) -> CommandResult:
    """Run a linter against the session's touched files (or `args`).

    Auto-detects: ruff/flake8 for Python, eslint for JS/TS, gofmt -l for
    Go, clippy for Rust. Falls back to /verify when nothing matches.
    """
    import shutil
    from pathlib import Path

    from ._changes import current_changelog
    from ._verify import run_check

    arg = args.strip()
    if arg:
        files = arg.split()
    else:
        files = current_changelog().files_touched()
    if not files:
        console.print(
            "[meta](no files to lint — pass paths or make some agent changes first)[/meta]"
        )
        return "continue"

    first = files[0]
    cwd = Path(session.cwd)
    cmd: str | None = None
    if first.endswith(".py"):
        for cand in ("ruff check", "flake8"):
            if shutil.which(cand.split()[0]):
                cmd = f"{cand} {' '.join(files)}"
                break
    elif first.endswith((".ts", ".tsx", ".js", ".jsx")):
        if shutil.which("eslint"):
            cmd = f"eslint {' '.join(files)}"
        elif (cwd / "node_modules" / ".bin" / "eslint").exists():
            cmd = f"./node_modules/.bin/eslint {' '.join(files)}"
    elif first.endswith(".go"):
        cmd = f"gofmt -l {' '.join(files)}"
    elif first.endswith(".rs"):
        cmd = "cargo clippy --quiet"

    if cmd is None:
        console.print("[meta]no linter detected; falling back to /verify[/meta]")
        return _cmd_verify(console, session, "")

    console.print(f"[meta]running:[/meta] [key]{cmd}[/key]")
    with console.status("[brand]linting…[/brand]"):
        result = run_check(cmd, cwd=session.cwd)
    style = "ok" if result.ok else "err"
    console.print(
        f"[{style}]{'CLEAN' if result.ok else 'ISSUES'}[/{style}] "
        f"[meta]exit={result.exit_code}[/meta]"
    )
    if result.head.strip():
        from rich.panel import Panel

        console.print(Panel(result.head, border_style=style, padding=(0, 1)))
    return "continue"


def _cmd_diff(console: Console, session: Session, args: str) -> CommandResult:
    """Show every file change the agent made this session, one panel per file."""
    from ._changes import current_changelog
    from ._diff_render import render_diff_pretty

    log = current_changelog()
    body = log.diff()
    if not body.strip():
        console.print("[meta](no changes this session)[/meta]")
        return "continue"
    render_diff_pretty(console, body)
    return "continue"


def _cmd_undo(console: Console, session: Session, args: str) -> CommandResult:
    """Revert the most recent agent-applied change."""
    from pathlib import Path

    from ._changes import current_changelog

    log = current_changelog()
    entry = log.undo_last(sandbox_root=Path(session.cwd))
    if entry is None:
        console.print("[meta](nothing to undo)[/meta]")
        return "continue"
    kind_lbl = {"create": "deleted", "modify": "restored", "delete": "restored"}.get(
        entry.kind, "reverted"
    )
    console.print(f"[ok]{kind_lbl}[/ok] [brand]{entry.path}[/brand]")
    return "continue"


def _cmd_commit(console: Console, session: Session, args: str) -> CommandResult:
    """Create a git commit of the session's changes."""
    import shutil
    import subprocess
    from pathlib import Path

    from ._changes import current_changelog

    log = current_changelog()
    if not log.entries:
        console.print("[meta](no changes to commit)[/meta]")
        return "continue"
    if shutil.which("git") is None:
        console.print("[err]git not on PATH[/err]")
        return "continue"
    cwd = Path(session.cwd)
    if not (cwd / ".git").exists():
        # Walk up looking for .git
        for parent in cwd.parents:
            if (parent / ".git").exists():
                break
        else:
            console.print(f"[err]no git repo at or above {cwd}[/err]")
            return "continue"
    message = args.strip() or f"essarion: {len(log.entries)} change(s) in session {session.id}"
    files = log.files_touched()
    try:
        subprocess.run(
            ["git", "add", "--"] + files, cwd=str(cwd), check=True, capture_output=True
        )
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=str(cwd), check=False, capture_output=True, text=True,
        )
        if result.returncode != 0:
            console.print(f"[err]git commit failed:[/err]\n{result.stderr.strip()}")
            return "continue"
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(cwd), check=True, capture_output=True, text=True,
        ).stdout.strip()
        console.print(f"[ok]committed[/ok] [brand]{sha}[/brand] [meta]{message}[/meta]")
    except subprocess.CalledProcessError as e:
        console.print(f"[err]git error: {e}[/err]")
    return "continue"


def _cmd_stream(console: Console, session: Session, args: str) -> CommandResult:
    """Toggle streamed draft output (tokens land as they're generated)."""
    arg = args.strip().lower()
    if arg == "on":
        session.stream = True
    elif arg == "off":
        session.stream = False
    elif arg == "":
        session.stream = not session.stream
    else:
        console.print("[err]usage: /stream [on|off][/err]")
        return "continue"
    state = "ON" if session.stream else "OFF"
    style = "ok" if session.stream else "meta"
    console.print(f"[{style}]streaming: {state}[/{style}]")
    return "continue"


def _cmd_auto(console: Console, session: Session, args: str) -> CommandResult:
    """Toggle autonomous ("auto") mode — ON by default.

    When ON (the default), a task is planned internally and then executed
    autonomously with real disk tools (write/edit/delete/run_shell) in a loop
    until the goal is done — no approval stop. When OFF, the agent falls back to
    the classic plan → approve → hand-apply-one-change flow.
    """
    arg = args.strip().lower()
    if arg == "on":
        session.autonomous = True
    elif arg == "off":
        session.autonomous = False
    elif arg == "":
        session.autonomous = not session.autonomous
    else:
        console.print("[err]usage: /auto [on|off][/err]")
        return "continue"
    state = "ON" if session.autonomous else "OFF"
    style = "ok" if session.autonomous else "meta"
    console.print(f"[{style}]autonomous mode: {state}[/{style}]")
    if session.autonomous:
        console.print(
            "[hint]tasks now plan internally then run end-to-end on disk "
            "(write/edit/delete/shell) until done — no approval stop. "
            "/undo and /diff still work.[/hint]"
        )
    else:
        console.print(
            "[hint]plan-first mode: you'll see the plan, approve it, then apply "
            "one change by hand.[/hint]"
        )
    return "continue"


def _cmd_goal(console: Console, session: Session, args: str) -> CommandResult:
    """Pursue a goal autonomously until it's accomplished — no stops.

    Unlike a normal task (which plans, asks you to approve, runs once, and
    returns), /goal pre-approves the plan and keeps working — continuing past
    step caps round after round — until the agent emits <done> or the budget
    runs out. Implies autonomous mode.

    Usage: /goal <what you want accomplished>
      /goal run all tests and fix any failures
      /goal build a REST API for todos with tests, then run them
    """
    goal = args.strip()
    if not goal:
        console.print("[err]usage: /goal <what you want accomplished>[/err]")
        console.print("[hint]e.g. /goal run all tests and fix failures[/hint]")
        return "continue"
    from ._loop import run_goal

    try:
        run_goal(console, session, goal)
    except KeyboardInterrupt:
        console.print("\n[warn]🎯 goal halted.[/warn]")
    return "continue"


def _cmd_computer(console: Console, session: Session, args: str) -> CommandResult:
    """Toggle computer use — let the agent drive a real browser (reactive, opt-in).

    When ON, the agent gains the browser_* tools and acts→observes→acts on a live
    page. Implies autonomous mode. Off by default. Needs the [computer] extra
    (`pip install 'essarion-build[computer]'` + `playwright install chromium`)
    for the real browser; a vision model is only needed for screenshots.
    """
    arg = args.strip().lower()
    if arg == "on":
        session.computer_use = True
    elif arg == "off":
        session.computer_use = False
    elif arg == "":
        session.computer_use = not session.computer_use
    else:
        console.print("[err]usage: /computer [on|off][/err]")
        return "continue"
    if session.computer_use:
        session.autonomous = True  # act→observe→act needs the autonomous loop
        console.print("[ok]computer use: ON[/ok]")
        from ..computer import check_vision

        ok, msg = check_vision(session.provider, session.model)
        if not ok:
            console.print(f"[warn]note:[/warn] {msg}")
        console.print(
            "[hint]the agent can now open a browser, click/type, and read a digest "
            "of what changed. say what you want tested.[/hint]"
        )
    else:
        console.print("[meta]computer use: OFF[/meta]")
    return "continue"


def _cmd_desktop(console: Console, session: Session, args: str) -> CommandResult:
    """Toggle DESKTOP control — drive the real machine's mouse/keyboard/screen.

    Off by default and gated: it can do anything you can. Implies autonomous.
    Needs the [desktop] extra (`pip install 'essarion-build[desktop]'`) and a
    display. Prefer a contained display/VM you trust.
    """
    arg = args.strip().lower()
    if arg == "off":
        session.desktop_control = False
        console.print("[meta]desktop control: OFF[/meta]")
        return "continue"
    if arg not in ("on", ""):
        console.print("[err]usage: /desktop [on|off][/err]")
        return "continue"

    from ._computer import DESKTOP_WARNING

    console.print(f"[err]{DESKTOP_WARNING}[/err]")
    confirm = _ui.prompt_text(
        console, "[err]type 'I understand' to enable desktop control[/err]", default=""
    ).strip().lower()
    if confirm not in ("i understand", "i understand."):
        console.print("[meta]desktop control NOT enabled.[/meta]")
        return "continue"
    session.desktop_control = True
    session.autonomous = True
    console.print("[ok]desktop control: ON[/ok]")
    from ..computer import check_vision

    ok, msg = check_vision(session.provider, session.model)
    if not ok:
        console.print(f"[warn]note:[/warn] {msg}")
    return "continue"


def _cmd_effort(console: Console, session: Session, args: str) -> CommandResult:
    """Show or set the reasoning effort level.

    Usage:
      /effort                 show current level + what each costs
      /effort auto            tiny triage sizes each task, then routes
      /effort quick           plan only (1 call) — trivial tasks
      /effort standard        plan + self-check (2 calls)
      /effort deep            + critique + revise (4 calls)
      /effort max             + alternative-plan + synthesis (6 calls)
    """
    from .. import VALID_EFFORTS, approx_reason_calls
    from rich.table import Table

    arg = args.strip().lower()
    if not arg:
        table = Table(title="reasoning effort", title_style="brand")
        table.add_column("level", style="key")
        table.add_column("reason calls", justify="right", style="meta")
        table.add_column("what it adds", style="meta")
        rows = {
            "quick": "plan only — trivial tasks",
            "standard": "plan + adversarial self-check",
            "deep": "+ critique the plan, then revise it",
            "max": "+ explore an alternative plan, then synthesize",
            "auto": "triage sizes the task, routes to quick/standard/deep",
        }
        for level, desc in rows.items():
            calls = "1-4*" if level == "auto" else str(approx_reason_calls(level))
            marker = "  ← current" if level == session.effort else ""
            table.add_row(level + marker, calls, desc)
        console.print(table)
        console.print(
            "[hint]* auto = 1 triage call + the resolved level. "
            "Deeper levels refine the (short) plan, so they stay cheap "
            "relative to drafting code.[/hint]"
        )
        return "continue"

    if arg not in VALID_EFFORTS:
        console.print(
            f"[err]unknown effort {arg!r}. choose: {', '.join(VALID_EFFORTS)}[/err]"
        )
        return "continue"
    session.effort = arg
    console.print(f"[ok]reasoning effort set to [/ok][phase.plan]{arg}[/phase.plan]")
    if arg == "max":
        console.print(
            "[hint]max is 6 reasoning calls per turn — use it for "
            "irreversible or security-critical work.[/hint]"
        )
    return "continue"


def _cmd_cost(console: Console, session: Session, args: str) -> CommandResult:
    """Show projected and actual cost.

    With no args: print the session ledger (per-turn, total).
    With a path/dir: estimate the cost of running a turn against it.
    """
    from rich.table import Table

    from ._pricing import estimate_turn_cost_usd, format_cost

    arg = args.strip()
    if arg:
        # Estimate against a hypothetical context that loaded `arg` from disk.
        from .. import Context
        from pathlib import Path

        ctx = Context()
        path = Path(session.cwd) / arg
        if path.is_file():
            ctx.add_file(path)
        elif path.is_dir():
            ctx.add_repo(path, max_files=200)
        else:
            console.print(f"[err]not a file or directory: {arg}[/err]")
            return "continue"
        tokens, projected = estimate_turn_cost_usd(
            ctx,
            provider=session.provider,
            model=session.model,
            max_tokens=session.max_tokens,
        )
        console.print(
            f"[meta]target [/meta][brand]{arg}[/brand][meta] · "
            f"~{tokens:,} tokens · projected [/meta]"
            f"[brand]{format_cost(projected)}[/brand]"
        )
        return "continue"

    # Per-turn ledger.
    if not session.history:
        console.print("[meta](no turns this session)[/meta]")
        return "continue"

    table = Table(title="session cost", title_style="brand")
    table.add_column("#", style="meta", justify="right")
    table.add_column("task", style="key")
    table.add_column("tokens", justify="right", style="meta")
    table.add_column("cost", justify="right", style="brand")
    for i, turn in enumerate(session.history, 1):
        table.add_row(
            str(i),
            turn.task[:60],
            f"{turn.usage.total_tokens:,}",
            format_cost(turn.cost_usd),
        )
    console.print(table)
    console.print(
        f"[brand]total[/brand]: "
        f"[brand]{session.total_usage.total_tokens:,}[/brand] tokens · "
        f"[brand]{format_cost(session.total_cost_usd)}[/brand] "
        f"[meta]of budget ${session.budget_usd:.2f}[/meta]"
    )

    # Runway projection: at current cost-per-turn, how many more turns fit?
    n = len(session.history)
    if n > 0 and session.budget_usd > 0:
        avg_cost = session.total_cost_usd / n if n else 0
        remaining = max(0.0, session.budget_usd - session.total_cost_usd)
        runway = int(remaining / avg_cost) if avg_cost > 0 else 999
        runway_style = "ok" if runway >= 5 else ("warn" if runway >= 1 else "err")
        console.print(
            f"[meta]avg/turn: {format_cost(avg_cost)}  "
            f"·  budget left: [/meta][brand]{format_cost(remaining)}[/brand]"
            f"[meta]  ·  runway: [/meta][{runway_style}]≈{runway} turn(s)[/{runway_style}]"
        )
    return "continue"


def _env_is_gitignored(cwd) -> bool:
    """Whether `.env` is covered by `.gitignore` (so a saved key won't be committed)."""
    from pathlib import Path

    gi = Path(cwd) / ".gitignore"
    if not gi.is_file():
        return False
    try:
        for line in gi.read_text(encoding="utf-8").splitlines():
            if line.strip() in {".env", "*.env", ".env*", "/.env", ".env.*"}:
                return True
    except OSError:
        pass
    return False


def _keys_set(console: Console, session: Session, rest: str) -> CommandResult:
    """`/keys set <provider> [key] [save]` — capture a provider key for this
    session (and optionally persist it to `.env`). Omit the key to be prompted
    without echo. Append `save` to write it to `.env` non-interactively."""
    import os

    tokens = rest.split()
    provider = (tokens[0] if tokens else session.provider).strip().lower()
    envs = _PROVIDER_ENVS.get(provider)
    if envs is None:
        console.print(f"[err]unknown provider {provider!r}. known: {', '.join(_PROVIDER_ENVS)}[/err]")
        return "continue"
    if not envs:
        console.print(f"[meta]{provider} needs no API key.[/meta]")
        return "continue"
    env_var = envs[0]
    rest_tokens = tokens[1:]
    save = bool(rest_tokens) and rest_tokens[-1].lower() == "save"
    if save:
        rest_tokens = rest_tokens[:-1]
    key = rest_tokens[0] if rest_tokens else ""

    if not key:
        # Prompt without echo when interactive; otherwise we can't capture it.
        import getpass
        import sys

        if getattr(sys.stdin, "isatty", lambda: False)():
            try:
                key = getpass.getpass(f"{env_var} (input hidden): ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("[meta]cancelled.[/meta]")
                return "continue"
        else:
            console.print(f"[err]usage: /keys set {provider} <key> [save][/err]")
            return "continue"
    if not key:
        console.print("[meta]no key entered.[/meta]")
        return "continue"

    os.environ[env_var] = key
    console.print(f"[ok]{env_var} set for this session[/ok]")

    # Persist to .env (so it survives a restart) when asked, or offered interactively.
    if not save:
        import sys

        if getattr(sys.stdin, "isatty", lambda: False)() and getattr(sys.stdout, "isatty", lambda: False)():
            ans = _ui.prompt_text(
                console, "[brand]save to .env so it persists across restarts? (y/N)[/brand]",
                default="N",
            ).strip().lower()
            save = ans in {"y", "yes"}
    if save:
        from pathlib import Path

        from ._dotenv import upsert_dotenv

        env_path = Path(session.cwd) / ".env"
        try:
            upsert_dotenv(env_path, env_var, key)
        except OSError as e:
            console.print(f"[err]could not write {env_path}: {e}[/err]")
            return "continue"
        console.print(f"[ok]saved {env_var} → {env_path}[/ok]")
        if not _env_is_gitignored(session.cwd):
            console.print(
                "[warn]heads up:[/warn] .env isn't in .gitignore — add it so the key "
                "isn't committed."
            )
    else:
        console.print(
            "[hint]set for this session only. add `save` (or say yes) to persist it "
            "to .env.[/hint]"
        )
    return "continue"


def _cmd_keys(console: Console, session: Session, args: str) -> CommandResult:
    """Show which provider API keys are set, or set one.

    `/keys`                       table of which provider keys are present
    `/keys set <provider> [key]`  capture a key (hidden prompt if omitted),
                                  optionally persisting it to `.env`

    Never prints key values — only whether they exist.
    """
    arg = args.strip()
    if arg.lower() == "set" or arg.lower().startswith("set "):
        return _keys_set(console, session, arg[3:].strip())

    import os
    from rich.table import Table

    from .. import list_providers

    table = Table(title="provider keys", title_style="brand")
    table.add_column("provider", style="key")
    table.add_column("env var", style="meta")
    table.add_column("set?")
    for prov in list_providers():
        envs = _PROVIDER_ENVS.get(prov)
        if envs is None:
            env_label, status = "(unknown)", "[meta](unknown)[/meta]"
        elif not envs:
            env_label, status = "(no key needed)", "[meta](no key needed)[/meta]"
        else:
            env_label = " / ".join(envs)
            status = "[ok]yes[/ok]" if any(os.environ.get(e) for e in envs) else "[err]no[/err]"
        marker = " [hint]← current[/hint]" if prov == session.provider else ""
        table.add_row(prov, env_label, status + marker)
    console.print(table)
    console.print("[hint]added a key to .env? run [key]/reload[/key] to pick it up without restarting.[/hint]")
    return "continue"


def _cmd_reload(console: Console, session: Session, args: str) -> CommandResult:
    """Hot-reload credentials/config without restarting the REPL.

    Re-reads `.env` (project root + cwd) into the environment and re-applies
    `essarion.toml` defaults, so a key you just added — or a default you
    changed — takes effect on the next task. No restart, no lost session state.
    This removes the one rough edge where a missing API key meant killing and
    relaunching the agent.
    """
    import os

    from ._dotenv import default_env_paths, load_dotenv_files
    from ._project import find_project_root

    project = find_project_root(session.cwd)
    paths = default_env_paths(session.cwd, project.root)
    found = [p for p in paths if p.is_file()]
    for p in found:
        console.print(f"[ok]reloaded[/ok] [brand]{p}[/brand]")
    # Explicit reload overrides — picking up a key you just changed is the point.
    loaded = load_dotenv_files(found, override=True)
    found_any = bool(found)

    # Re-read config-file defaults (provider/model/triage/max_tokens). These feed
    # the SDK defaults; the active session keeps the model you chose.
    try:
        from .._config_file import load_config_file

        _data, used = load_config_file()
        if used:
            console.print(f"[meta]reloaded config defaults from[/meta] {used}")
    except Exception as e:  # noqa: BLE001 - config reload is best-effort
        console.print(f"[warn]config reload skipped: {type(e).__name__}: {e}[/warn]")

    if loaded:
        console.print(
            "[meta]env keys now set:[/meta] " + ", ".join(f"[key]{k}[/key]" for k in loaded)
        )
    elif not found_any:
        console.print("[meta]no .env file found at the project root or cwd — nothing to reload.[/meta]")

    # Tell the user plainly whether the *current* provider is now usable.
    envs = _PROVIDER_ENVS.get(session.provider)
    if envs:
        if any(os.environ.get(e) for e in envs):
            console.print(f"[ok]{session.provider} key is set — ready for the next task.[/ok]")
        else:
            _warn_if_key_missing(console, session.provider)
    return "continue"


def _cmd_workflows_list(console: Console, session: Session, args: str) -> CommandResult:
    """List every available high-level workflow + its slash shortcut."""
    from rich.table import Table

    from .. import workflows

    table = Table(title="workflows", title_style="brand")
    table.add_column("slash", style="key")
    table.add_column("workflow", style="meta")
    table.add_column("what it does", style="meta")
    mapping = {
        "/review": "review",
        "/fix": "fix_bug",
        "/tests": "write_tests",
        "/refactor": "refactor",
        "/docs": "docs",
        "/security": "security_review",
        "/perf": "performance_review",
        "/explain": "explain_code",
        "/pr": "write_pr_description",
    }
    for slash, name in mapping.items():
        fn = getattr(workflows, name, None)
        desc = (fn.__doc__ or "").strip().split("\n", 1)[0] if fn else ""
        table.add_row(slash, name, desc[:80])
    console.print(table)
    console.print(
        "[hint]invoke via `/<slash> <target>` or by prefixing your task "
        "with `<verb>:` (e.g. `review: src/auth.py`).[/hint]"
    )
    return "continue"


def _cmd_hooks(console: Console, session: Session, args: str) -> CommandResult:
    """List the lifecycle hooks configured in `.essarion/config.toml`."""
    from rich.table import Table

    from . import _hooks

    hooks = _hooks.list_hooks()
    if not hooks:
        console.print("[meta]no hooks configured.[/meta]")
        console.print(
            "[hint]add `[[hooks]]` blocks to .essarion/config.toml — events: "
            + ", ".join(sorted(_hooks.EVENTS))
            + ". e.g. format on write:\n"
            '  [[hooks]]\n  event = "post_tool"\n  matcher = "write_file"\n'
            '  command = "ruff format ."[/hint]'
        )
        return "continue"
    table = Table(title="hooks", title_style="brand")
    table.add_column("event", style="key")
    table.add_column("matcher", style="meta")
    table.add_column("name", style="meta")
    table.add_column("command", style="meta")
    for h in hooks:
        table.add_row(h.event, h.matcher, h.name or "—", h.command[:60])
    console.print(table)
    return "continue"


def _cmd_mcp(console: Console, session: Session, args: str) -> CommandResult:
    """Show connected MCP servers + their tools; `/mcp reconnect` retries.

    Servers are declared as `[[mcp_servers]]` blocks in `.essarion/config.toml`
    (or `~/.config/essarion/config.toml`).
    """
    from rich.table import Table

    from . import _mcp

    mgr = _mcp.current_manager()

    if args.strip().lower() in {"reconnect", "reload", "retry"}:
        mgr.shutdown()
        _mcp.startup_from_config(console, session.cwd)

    if not mgr.clients and not mgr.errors:
        console.print("[meta]no MCP servers configured.[/meta]")
        console.print(
            "[hint]declare one in .essarion/config.toml:\n"
            "  [[mcp_servers]]\n"
            '  name = "github"\n'
            '  command = "npx -y @modelcontextprotocol/server-github"\n'
            "then /mcp reconnect. Its tools become callable as "
            "mcp__github__<tool>.[/hint]"
        )
        return "continue"

    table = Table(title="MCP servers", title_style="brand")
    table.add_column("server", style="key")
    table.add_column("status", style="meta")
    table.add_column("tools", style="meta")
    for name, client in sorted(mgr.clients.items()):
        status = "connected" if client.alive else f"dead ({client.dead_reason or 'stopped'})"
        tools = ", ".join(t["name"] for t in client.tools[:8])
        if len(client.tools) > 8:
            tools += f" (+{len(client.tools) - 8} more)"
        table.add_row(name, status, tools or "—")
    for name, err in sorted(mgr.errors.items()):
        if name not in mgr.clients:
            table.add_row(name, f"failed — {err[:80]}", "—")
    console.print(table)
    console.print("[hint]/mcp reconnect to retry failed/dead servers.[/hint]")
    return "continue"


def _cmd_summary(console: Console, session: Session, args: str) -> CommandResult:
    """One-paragraph summary of what the agent did this session.

    Useful as a basis for a commit message or a PR description.
    """
    from rich.panel import Panel

    if not session.history:
        console.print("[meta](no turns this session)[/meta]")
        return "continue"

    from ._changes import current_changelog

    log = current_changelog()
    lines = [
        f"Session {session.id} ({len(session.history)} turn(s)):",
        "",
    ]
    for i, turn in enumerate(session.history, 1):
        first_plan = (turn.plan or turn.verdict or "(no plan)").splitlines()
        head = (first_plan[0] if first_plan else "(no plan)").lstrip("- 0123456789.").strip()
        lines.append(f"  {i}. {turn.task[:80]}")
        if head:
            lines.append(f"     plan: {head[:120]}")
        if turn.files_touched:
            lines.append(f"     files: {', '.join(turn.files_touched)}")
    files = log.files_touched()
    if files:
        lines.append("")
        lines.append(f"files touched: {', '.join(files)}")
    lines.append("")
    lines.append(
        f"total: {session.total_usage.total_tokens:,} tokens · "
        f"${session.total_cost_usd:.4f}"
    )
    console.print(
        Panel(
            "\n".join(lines),
            title="[brand]session summary[/brand]",
            border_style="brand",
            padding=(0, 1),
        )
    )
    return "continue"


def _cmd_whoami(console: Console, session: Session, args: str) -> CommandResult:
    """One-screen status: project + model + memory + sessions dir."""
    from rich.table import Table

    from .. import __version__
    from ._memory import load_memory
    from ._project import find_project_root

    project = find_project_root(session.cwd)
    memory = load_memory(session.cwd)

    table = Table.grid(padding=(0, 2))
    table.add_column(style="meta", justify="right")
    table.add_column()
    table.add_row("essarion", f"[brand]{__version__}[/brand]")
    table.add_row("session", session.id)
    if project.detected_by:
        table.add_row(
            "project",
            f"{project.root}  [hint]({project.detected_by})[/hint]",
        )
    else:
        table.add_row("cwd", session.cwd)
    table.add_row("sessions dir", str(project.sessions_dir))
    table.add_row(
        "model",
        f"{session.provider}/[brand]{session.model}[/brand]"
        + (f"  [meta]escalate→[/meta] {session.escalate_model}" if session.escalate_model else "")
        + (f"  [meta]triage→[/meta] {session.triage_model}" if session.triage_model else "")
        + (f"  [meta]2nd→[/meta] {session.crosscheck_model}" if session.crosscheck_model else ""),
    )
    table.add_row(
        "skills",
        f"picker mode [brand]{session.skills_mode}[/brand]",
    )
    table.add_row(
        "reasoning",
        f"effort [brand]{session.effort}[/brand]",
    )
    table.add_row(
        "budget",
        f"${session.total_cost_usd:.4f} / [brand]${session.budget_usd:.2f}[/brand]",
    )
    table.add_row(
        "memory",
        f"{len(memory.facts)} fact(s)  [hint]({memory.path})[/hint]",
    )
    table.add_row(
        "turns",
        str(len(session.history)),
    )
    # Background tasks if any.
    try:
        from . import _background as bg

        running = bg.current_manager().running_count()
        if running:
            table.add_row("bg tasks", f"[warn]{running} running[/warn]")
    except Exception:  # noqa: BLE001
        pass
    console.print(table)
    return "continue"


def _cmd_ask(console: Console, session: Session, args: str) -> CommandResult:
    """Quick Q&A: runs reason() only (no draft), prints the plan inline."""
    from ._loop import _build_context, _run_plan_phase
    from ._session import TaskTurn
    from pathlib import Path

    task = args.strip()
    if not task:
        console.print("[err]usage: /ask <question>[/err]")
        return "continue"
    ctx, picks, why = _build_context(
        task, session=session, cwd=Path(session.cwd), console=console
    )
    if picks:
        from ._ui import render_skills_picked

        render_skills_picked(console, picks, why)
    turn = TaskTurn(task=task, skills_used=picks)
    r = _run_plan_phase(console, session, ctx, task, turn)
    if r is not None:
        turn.plan = r.plan
        turn.tradeoffs = r.tradeoffs
        turn.verdict = r.verdict
    session.record(turn)
    from ._ui import render_footer

    render_footer(console, session)
    return "continue"


def _workflow_command(workflow_key: str):
    """Build a slash command that routes to one of the SDK workflows."""

    def _cmd(console: Console, session: Session, args: str) -> CommandResult:
        from ._loop import run_turn

        target = args.strip()
        if not target:
            console.print(f"[err]usage: /{workflow_key} <target>[/err]")
            return "continue"
        # Map slash name to the workflow prefix the loop already recognizes.
        prefix = {
            "review": "review",
            "fix": "fix-bug",
            "tests": "tests",
            "refactor": "refactor",
            "docs": "docs",
            "security": "security-review",
            "perf": "perf-review",
            "explain": "explain",
            "pr": "pr-description",
        }[workflow_key]
        run_turn(console, session, f"{prefix}: {target}")
        return "continue"

    return _cmd


def _cmd_bg(console: Console, session: Session, args: str) -> CommandResult:
    """Background task management.

    Usage:
      /bg                         list every running/finished task
      /bg <shell command>         start a new background task
      /bg run <cmd>               same as above (explicit)
      /bg detached <cmd>          start one that survives REPL exit
      /bg show <id>               print status + recent output of task <id>
      /bg wait <id> [seconds]     block until <id> finishes
      /bg kill <id>               terminate task <id>
      /bg clear                   forget all finished tasks
    """
    from . import _background as bg

    mgr = bg.current_manager()
    arg = args.strip()

    def _show_one(task_id: str) -> None:
        try:
            task = mgr.poll(task_id)
        except KeyError:
            console.print(f"[err]unknown task: {task_id}[/err]")
            return
        head = (
            f"[brand][{task.id}][/brand] [key]{task.name}[/key]  "
            f"status=[brand]{task.status}[/brand]"
            + (f" exit={task.exit_code}" if task.exit_code is not None else "")
            + f"  elapsed={task.elapsed_seconds:.1f}s"
        )
        console.print(head)
        body = mgr.tail(task.id, lines=30)
        if body.strip():
            from rich.panel import Panel

            console.print(Panel(body, border_style="meta", padding=(0, 1)))

    if not arg:
        tasks = mgr.poll_all()
        if not tasks:
            console.print("[meta](no background tasks — start one with /bg <cmd>)[/meta]")
            return "continue"
        from rich.table import Table

        table = Table(title="background tasks", title_style="brand")
        table.add_column("id", style="key")
        table.add_column("status")
        table.add_column("name", style="meta")
        table.add_column("elapsed", justify="right", style="meta")
        table.add_column("exit", justify="right", style="meta")
        for t in tasks:
            status_style = {"running": "warn", "done": "ok", "failed": "err", "killed": "err"}.get(t.status, "meta")
            table.add_row(
                t.id,
                f"[{status_style}]{t.status}[/{status_style}]",
                t.name[:60],
                f"{t.elapsed_seconds:.1f}s",
                "" if t.exit_code is None else str(t.exit_code),
            )
        console.print(table)
        return "continue"

    parts = arg.split(maxsplit=1)
    head = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    if head == "clear":
        n = mgr.clear_finished()
        console.print(f"[ok]cleared {n} finished task(s)[/ok]")
        return "continue"

    if head == "show":
        if not rest:
            console.print("[err]usage: /bg show <id>[/err]")
            return "continue"
        _show_one(rest.strip())
        return "continue"

    if head == "wait":
        wparts = rest.split()
        if not wparts:
            console.print("[err]usage: /bg wait <id> [seconds][/err]")
            return "continue"
        task_id = wparts[0]
        try:
            timeout = float(wparts[1]) if len(wparts) > 1 else 60.0
        except ValueError:
            console.print("[err]usage: /bg wait <id> [seconds][/err]")
            return "continue"
        with console.status(f"[brand]waiting for {task_id} (≤{timeout:.0f}s)…[/brand]"):
            try:
                task = mgr.wait(task_id, timeout=timeout)
            except KeyError:
                console.print(f"[err]unknown task: {task_id}[/err]")
                return "continue"
        _show_one(task.id)
        return "continue"

    if head == "kill":
        if not rest:
            console.print("[err]usage: /bg kill <id>[/err]")
            return "continue"
        try:
            task = mgr.kill(rest.strip())
        except KeyError:
            console.print(f"[err]unknown task: {rest.strip()}[/err]")
            return "continue"
        console.print(f"[ok]killed [{task.id}] (exit {task.exit_code})[/ok]")
        return "continue"

    detached = False
    if head == "detached":
        detached = True
        cmd = rest
    elif head == "run":
        cmd = rest
    else:
        cmd = arg

    if not cmd.strip():
        console.print("[err]usage: /bg <shell command>[/err]")
        return "continue"

    task = mgr.start(cmd, detached=detached)
    if task.is_running:
        suffix = " [warn](detached)[/warn]" if detached else ""
        console.print(
            f"[ok]started[/ok] [brand][{task.id}][/brand] "
            f"[meta]pid={task.pid} · {task.name}[/meta]{suffix}"
        )
    else:
        detail = " ".join(task.stderr_tail).strip() or task.status
        console.print(f"[err]failed to start[/err]: {detail}")
    return "continue"

# Public dispatch table: name → (function, description).
COMMANDS: dict[str, tuple[Callable, str]] = {
    "/help": (_cmd_help, "show this list"),
    "/quit": (_cmd_quit, "exit the agent"),
    "/clear": (_cmd_clear, "clear the screen"),
    "/budget": (_cmd_budget, "show cost so far, or set a spending cap (no cap by default)"),
    "/model": (_cmd_model, "show or set the provider/model"),
    "/escalate": (_cmd_escalate, "set or clear the escalation model"),
    "/triage": (_cmd_triage, "set the cheap model for effort=auto routing (de-escalation)"),
    "/crosscheck": (_cmd_crosscheck, "set a 2nd model to independently review every change"),
    "/skills": (_cmd_skills, "list skills or set picker mode (auto|all|none)"),
    "/cd": (_cmd_cd, "change the sandbox cwd"),
    "/pwd": (_cmd_pwd, "print the sandbox cwd"),
    "/map": (_cmd_map, "show the repo map (ranked symbol skeleton); args bias the ranking"),
    "/outline": (_cmd_outline, "list one file's symbols + signatures: /outline <file>"),
    "/symbol": (_cmd_symbol, "find where a symbol is defined and referenced: /symbol <name>"),
    "/history": (_cmd_history, "list this session's turns"),
    "/save": (_cmd_save, "persist the session to the sessions dir"),
    "/load": (_cmd_load, "list saved sessions"),
    "/export": (_cmd_export, "dump session JSON to stdout"),
    "/yolo": (_cmd_yolo, "toggle auto-approval of side-effect tools"),
    "/bg": (_cmd_bg, "background tasks: run / list / show / wait / kill / clear"),
    "/remember": (_cmd_remember, "show or add a fact to project memory"),
    "/forget": (_cmd_forget, "remove fact(s) from project memory"),
    "/verify": (_cmd_verify, "run the project's check command (tests/lint)"),
    "/lint": (_cmd_lint, "lint the session's touched files (auto-detects ruff/eslint/clippy/gofmt)"),
    "/diff": (_cmd_diff, "show every change made this session"),
    "/undo": (_cmd_undo, "revert the most recent agent-applied change"),
    "/commit": (_cmd_commit, "git-commit the session's changes"),
    "/ask": (_cmd_ask, "quick reason() only, no draft phase"),
    "/cost": (_cmd_cost, "show session cost ledger or estimate against a path"),
    "/stream": (_cmd_stream, "toggle streamed draft output (token-by-token)"),
    "/goal": (_cmd_goal, "pursue a goal autonomously until done — no stops (e.g. /goal run all tests)"),
    "/auto": (_cmd_auto, "toggle autonomous mode (ON by default; off = plan→approve→hand-apply)"),
    "/computer": (_cmd_computer, "toggle computer use (drive a real browser; opt-in)"),
    "/desktop": (_cmd_desktop, "toggle DESKTOP control (real mouse/keyboard/screen; gated)"),
    "/effort": (_cmd_effort, "show or set reasoning depth (quick/standard/deep/max/auto)"),
    "/whoami": (_cmd_whoami, "one-screen status: project + model + memory + budget"),
    "/summary": (_cmd_summary, "one-paragraph summary of this session — useful for commits/PRs"),
    "/workflows": (_cmd_workflows_list, "list bundled workflows + their slash shortcuts"),
    "/hooks": (_cmd_hooks, "list lifecycle hooks from .essarion/config.toml"),
    "/mcp": (_cmd_mcp, "list connected MCP servers + tools; /mcp reconnect retries"),
    "/keys": (_cmd_keys, "show provider keys, or set one: /keys set <provider> [key]"),
    "/reload": (_cmd_reload, "hot-reload .env / config without restarting"),
    "/commands": (_cmd_help, "list every command (alias of /help)"),
    "/review": (_workflow_command("review"), "shortcut: workflows.review(<target>)"),
    "/fix": (_workflow_command("fix"), "shortcut: workflows.fix_bug(<target>)"),
    "/tests": (_workflow_command("tests"), "shortcut: workflows.write_tests(<target>)"),
    "/refactor": (_workflow_command("refactor"), "shortcut: workflows.refactor(<target>)"),
    "/docs": (_workflow_command("docs"), "shortcut: workflows.docs(<target>)"),
    "/security": (_workflow_command("security"), "shortcut: workflows.security_review(<target>)"),
    "/perf": (_workflow_command("perf"), "shortcut: workflows.performance_review(<target>)"),
    "/explain": (_workflow_command("explain"), "shortcut: workflows.explain_code(<target>)"),
    "/pr": (_workflow_command("pr"), "shortcut: workflows.write_pr_description(<target>)"),
    "/version": (_cmd_version, "show the SDK version"),
}



def _did_you_mean(unknown: str) -> str | None:
    """Suggest the closest slash command to `unknown`."""
    import difflib

    candidates = list(COMMANDS.keys())
    matches = difflib.get_close_matches(unknown, candidates, n=1, cutoff=0.6)
    return matches[0] if matches else None


def _try_custom_command(
    console: Console, session: Session, cmd: str, args: str
) -> CommandResult | None:
    """Look for a user-defined command in `<project>/.essarion/commands/`.

    Each file `<name>.md` becomes the slash command `/<name>`. The body
    is treated as a task template; the user's args after the slash
    command are substituted in for `{args}`.
    """
    from pathlib import Path

    from ._project import find_project_root
    from ._loop import run_task

    name = cmd.lstrip("/")
    if not name:
        return None
    project = find_project_root(session.cwd)
    candidates = []
    if project.has_essarion_dir:
        candidates.append(project.essarion_dir / "commands" / f"{name}.md")
    candidates.append(Path.home() / ".essarion" / "commands" / f"{name}.md")
    for path in candidates:
        if path.is_file():
            template = path.read_text(encoding="utf-8")
            task = template.replace("{args}", args).strip()
            if not task:
                console.print(
                    f"[err]custom command {cmd} produced an empty task[/err]"
                )
                return "continue"
            run_task(console, session, task)
            return "continue"
    return None


def dispatch(console: Console, session: Session, line: str) -> CommandResult | None:
    """Try to handle `line` as a slash command. Returns None if it isn't one."""
    if not line.startswith("/"):
        return None
    parts = line.split(maxsplit=1)
    cmd = parts[0]
    args = parts[1] if len(parts) > 1 else ""
    entry = COMMANDS.get(cmd)
    if entry is not None:
        fn, _ = entry
        return fn(console, session, args)
    # User-defined slash command from .essarion/commands/<name>.md ?
    custom = _try_custom_command(console, session, cmd, args)
    if custom is not None:
        return custom
    suggestion = _did_you_mean(cmd)
    if suggestion:
        console.print(
            f"[err]unknown command {cmd}[/err]  "
            f"[hint]did you mean [key]{suggestion}[/key]?[/hint]"
        )
    else:
        console.print(
            f"[err]unknown command {cmd}[/err]  [hint]/help to list them[/hint]"
        )
    return "continue"
