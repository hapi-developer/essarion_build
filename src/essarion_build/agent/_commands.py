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


_HELP_GROUPS: list[tuple[str, list[str]]] = [
    ("session", ["/whoami", "/history", "/summary", "/save", "/load", "/export", "/clear", "/version", "/quit"]),
    ("autonomy", ["/goal"]),
    ("planning", ["/ask"]),
    ("workflows", ["/workflows", "/review", "/fix", "/tests", "/refactor", "/docs", "/security", "/perf", "/explain", "/pr"]),
    ("reasoning", ["/effort"]),
    ("models & cost", ["/model", "/escalate", "/budget", "/cost", "/stream", "/keys"]),
    ("skills & memory", ["/skills", "/remember", "/forget"]),
    ("project & files", ["/cd", "/pwd"]),
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


def _cmd_budget(console: Console, session: Session, args: str) -> CommandResult:
    if args.strip():
        try:
            session.budget_usd = float(args.strip().lstrip("$"))
            console.print(f"[ok]budget set to ${session.budget_usd:.2f}[/ok]")
        except ValueError:
            console.print("[err]usage: /budget [amount-in-usd][/err]")
        return "continue"
    pct = session.budget_used_pct() * 100.0
    style = "cost.under" if pct < 60 else ("cost.warn" if pct < 90 else "cost.over")
    console.print(
        f"[meta]used[/meta] [{style}]${session.total_cost_usd:.4f}[/{style}]"
        f"[meta] / ${session.budget_usd:.2f}  ({pct:.1f}%)[/meta]"
    )
    return "continue"


def _cmd_model(console: Console, session: Session, args: str) -> CommandResult:
    args = args.strip()
    if not args:
        console.print(
            f"[meta]current:[/meta] [brand]{session.provider}/{session.model}[/brand]"
            + (f"  [meta](escalate to {session.escalate_model})[/meta]"
               if session.escalate_model else "")
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
    """Toggle autonomous ("auto") mode.

    When ON, an approved plan is executed autonomously with real disk tools
    (write/edit/delete/shell) until the goal is done, instead of producing one
    code blob to apply by hand.
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
            "[hint]approved plans now run end-to-end on disk "
            "(write/edit/delete/shell). /undo and /diff still work.[/hint]"
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


def _cmd_keys(console: Console, session: Session, args: str) -> CommandResult:
    """Show which provider API keys are set in the environment.

    Doesn't print the key values — only whether they exist. Useful for
    "why isn't this working?" debugging.
    """
    import os
    from rich.table import Table

    from .. import list_providers

    PROVIDER_ENVS = {
        "openrouter": "OPENROUTER_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "ollama": "(no key needed)",
        "stub": "(no key needed)",
    }
    table = Table(title="provider keys", title_style="brand")
    table.add_column("provider", style="key")
    table.add_column("env var", style="meta")
    table.add_column("set?")
    for prov in list_providers():
        env_var = PROVIDER_ENVS.get(prov, "(unknown)")
        if env_var.startswith("("):
            status = f"[meta]{env_var}[/meta]"
        else:
            # Also accept GOOGLE_API_KEY for Gemini.
            alt = "GOOGLE_API_KEY" if prov == "gemini" else None
            present = os.environ.get(env_var) or (alt and os.environ.get(alt))
            status = f"[ok]yes[/ok]" if present else f"[err]no[/err]"
        marker = ""
        if prov == session.provider:
            marker = " [hint]← current[/hint]"
        table.add_row(prov, env_var, status + marker)
    console.print(table)
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
        + (f"  [meta]escalate→[/meta] {session.escalate_model}" if session.escalate_model else ""),
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
        timeout = float(wparts[1]) if len(wparts) > 1 else 60.0
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
        console.print(f"[err]failed to start[/err]: {task.stderr_tail[:1]}")
    return "continue"

# Public dispatch table: name → (function, description).
COMMANDS: dict[str, tuple[Callable, str]] = {
    "/help": (_cmd_help, "show this list"),
    "/quit": (_cmd_quit, "exit the agent"),
    "/clear": (_cmd_clear, "clear the screen"),
    "/budget": (_cmd_budget, "show or set the session budget (USD)"),
    "/model": (_cmd_model, "show or set the provider/model"),
    "/escalate": (_cmd_escalate, "set or clear the escalation model"),
    "/skills": (_cmd_skills, "list skills or set picker mode (auto|all|none)"),
    "/cd": (_cmd_cd, "change the sandbox cwd"),
    "/pwd": (_cmd_pwd, "print the sandbox cwd"),
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
    "/auto": (_cmd_auto, "toggle autonomous mode (run approved plans on disk)"),
    "/computer": (_cmd_computer, "toggle computer use (drive a real browser; opt-in)"),
    "/desktop": (_cmd_desktop, "toggle DESKTOP control (real mouse/keyboard/screen; gated)"),
    "/effort": (_cmd_effort, "show or set reasoning depth (quick/standard/deep/max/auto)"),
    "/whoami": (_cmd_whoami, "one-screen status: project + model + memory + budget"),
    "/summary": (_cmd_summary, "one-paragraph summary of this session — useful for commits/PRs"),
    "/workflows": (_cmd_workflows_list, "list bundled workflows + their slash shortcuts"),
    "/hooks": (_cmd_hooks, "list lifecycle hooks from .essarion/config.toml"),
    "/keys": (_cmd_keys, "show which provider API keys are set in the env"),
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
    from ._loop import run_turn

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
            run_turn(console, session, task)
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
