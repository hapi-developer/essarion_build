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


def _cmd_help(console: Console, session: Session, args: str) -> CommandResult:
    table = Table(title="commands", title_style="brand", show_lines=False)
    table.add_column("command", style="key")
    table.add_column("description", style="meta")
    for name, (_fn, desc) in COMMANDS.items():
        table.add_row(name, desc)
    console.print(table)
    console.print(
        "\n[hint]anything that doesn't start with `/` is treated as a task.[/hint]"
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

    # No args → list
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

    # Subcommands
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

    # `/bg run <cmd>`, `/bg detached <cmd>`, or `/bg <cmd>` (treat whole arg as cmd)
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
    "/version": (_cmd_version, "show the SDK version"),
}


def dispatch(console: Console, session: Session, line: str) -> CommandResult | None:
    """Try to handle `line` as a slash command. Returns None if it isn't one."""
    if not line.startswith("/"):
        return None
    parts = line.split(maxsplit=1)
    cmd = parts[0]
    args = parts[1] if len(parts) > 1 else ""
    entry = COMMANDS.get(cmd)
    if entry is None:
        console.print(
            f"[err]unknown command {cmd}[/err]  [hint]/help to list them[/hint]"
        )
        return "continue"
    fn, _ = entry
    return fn(console, session, args)
