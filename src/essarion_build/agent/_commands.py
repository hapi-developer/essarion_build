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


def _cmd_diff(console: Console, session: Session, args: str) -> CommandResult:
    """Show every file change the agent made this session."""
    from ._changes import current_changelog
    from ._ui import render_diff

    log = current_changelog()
    body = log.diff()
    if not body.strip():
        console.print("[meta](no changes this session)[/meta]")
        return "continue"
    render_diff(console, body)
    console.print(
        f"[meta]files touched: {', '.join(log.files_touched()) or '(none)'}[/meta]"
    )
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


def _cmd_subagent(console: Console, session: Session, args: str) -> CommandResult:
    """Spawn focused subagents in parallel for the task.

    Usage:
      /subagent <task>                 spawn the default crew (researcher,
                                       implementer, test_writer) and synthesize
      /subagent <role1,role2>:<task>   spawn specific roles in parallel
    """
    arg = args.strip()
    if not arg:
        console.print(
            "[err]usage: /subagent <task>  ·  /subagent role1,role2:<task>[/err]"
        )
        console.print(
            "[hint]roles: researcher implementer test_writer verifier reviewer refactorer[/hint]"
        )
        return "continue"

    from ._loop import _dispatch_subagents

    _dispatch_subagents(console, session, arg)
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
    "/diff": (_cmd_diff, "show every change made this session"),
    "/undo": (_cmd_undo, "revert the most recent agent-applied change"),
    "/commit": (_cmd_commit, "git-commit the session's changes"),
    "/ask": (_cmd_ask, "quick reason() only, no draft phase"),
    "/subagent": (_cmd_subagent, "spawn parallel focused subagents (research/impl/tests/…)"),
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
    console.print(
        f"[err]unknown command {cmd}[/err]  [hint]/help to list them[/hint]"
    )
    return "continue"
