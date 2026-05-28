"""Agent entry point. Called by the `essarion` console script when no
existing CLI subcommand is given."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .._config import current
from ._loop import repl
from ._project import (
    Project,
    find_project_root,
    init_project,
    load_project_config,
)
from ._session import (
    Session,
    list_sessions,
    load_session,
    new_session_id,
)
from ._tools import bind_tools, register_all as _register_sdk_tools
from ._ui import make_console, show_banner


def _add_agent_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--task",
        help="run this task non-interactively and exit",
    )
    parser.add_argument(
        "--cwd",
        default=os.getcwd(),
        help="sandbox directory for tool calls (default: $PWD)",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=1.00,
        help="session budget in USD (default: 1.00)",
    )
    parser.add_argument(
        "--provider",
        help="provider for the agent (default: from configure() / env)",
    )
    parser.add_argument(
        "--model",
        help="model for the agent (default: from configure() / env)",
    )
    parser.add_argument(
        "--escalate",
        help="model to escalate to when selfcheck rejects",
    )
    parser.add_argument(
        "--skills",
        choices=["auto", "all", "none"],
        default="auto",
        help="skill-injection mode (default: auto — picker chooses 3-5)",
    )
    parser.add_argument(
        "--resume",
        help="resume a prior session by id (see /load inside the REPL)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        help="per-call token cap (default: from configure())",
    )


def build_agent_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="essarion",
        description="essarion build — a CLI coding agent. Plan-first, "
        "token-efficient, BYOK. Type `essarion` for the interactive REPL.",
    )
    _add_agent_args(parser)
    return parser


def _apply_project_config(
    args: argparse.Namespace, project: Project
) -> dict:
    """Mutate `args` to fold in `<project>/.essarion/config.toml` defaults.

    CLI flags always win. Returns the parsed config dict for inspection.
    """
    data = load_project_config(project)
    defaults = data.get("defaults", {}) or {}
    agent_cfg = data.get("agent", {}) or {}

    if args.provider is None and "provider" in defaults:
        args.provider = defaults["provider"]
    if args.model is None and "model" in defaults:
        args.model = defaults["model"]
    if args.max_tokens is None and "max_tokens" in defaults:
        args.max_tokens = int(defaults["max_tokens"])
    if args.escalate is None and "escalate_model" in agent_cfg:
        args.escalate = agent_cfg["escalate_model"] or None
    # `budget` and `skills` use argparse defaults so check against those.
    if args.budget == 1.00 and "budget" in agent_cfg:
        try:
            args.budget = float(agent_cfg["budget"])
        except (TypeError, ValueError):
            pass
    if args.skills == "auto" and "skills_mode" in agent_cfg:
        if agent_cfg["skills_mode"] in {"auto", "all", "none"}:
            args.skills = agent_cfg["skills_mode"]
    # The auto_route flag is read by the loop later from project config —
    # we don't fold it into argparse args, just stash it back via data.
    return data


def _initial_session(args: argparse.Namespace, project: Project) -> Session:
    """Build the Session object the REPL will mutate."""
    cfg = current()
    sessions_dir = project.sessions_dir

    if args.resume:
        s = load_session(args.resume, sessions_dir=sessions_dir)
        # Allow CLI overrides to win
        if args.cwd:
            s.cwd = str(Path(args.cwd).resolve())
        if args.provider:
            s.provider = args.provider
        if args.model:
            s.model = args.model
        if args.escalate is not None:
            s.escalate_model = args.escalate or None
        if args.skills:
            s.skills_mode = args.skills
        if args.max_tokens:
            s.max_tokens = args.max_tokens
        if args.budget:
            s.budget_usd = args.budget
        return s

    # New session, anchored to the project root.
    cwd = str(Path(args.cwd).resolve())
    return Session(
        id=new_session_id(),
        cwd=cwd,
        provider=args.provider or cfg.provider,
        model=args.model or cfg.model,
        escalate_model=args.escalate or None,
        max_tokens=args.max_tokens or cfg.max_tokens,
        budget_usd=args.budget,
        skills_mode=args.skills,
    )


def cmd_init(argv: list[str] | None = None) -> int:
    """`essarion init [<path>]` — create `.essarion/` in the chosen dir."""
    p = argparse.ArgumentParser(prog="essarion init", description="Initialize a project for the essarion agent.")
    p.add_argument("path", nargs="?", default=".", help="project root (default: cwd)")
    p.add_argument(
        "--with-memory",
        action="append",
        default=[],
        metavar="FACT",
        help="seed a fact into project memory (repeatable)",
    )
    args = p.parse_args(argv)
    project = init_project(args.path)
    console = make_console()
    console.print(
        f"[ok]initialized[/ok] [brand]{project.essarion_dir}[/brand]"
    )
    table_rows = [
        ("config", str(project.essarion_dir / "config.toml")),
        ("sessions", str(project.essarion_dir / "sessions")),
    ]

    if args.with_memory:
        from ._memory import load_memory

        memory = load_memory(args.path)
        for fact in args.with_memory:
            try:
                memory.add_fact(fact)
            except ValueError:
                continue
        memory.save()
        table_rows.append(("memory", f"{memory.path} ({len(memory.facts)} fact(s) seeded)"))

    for label, value in table_rows:
        console.print(f"[meta]{label}:[/meta] {value}")
    console.print(
        "\n[hint]next: type `essarion` (no args) to launch the REPL.[/hint]"
    )
    return 0


def run_agent(argv: list[str] | None = None) -> int:
    """Entry point invoked when the user types `essarion` (no subcommand).

    Returns an int suitable for sys.exit().
    """
    parser = build_agent_parser()
    args = parser.parse_args(argv)

    # Detect the project root; anchor the sandbox there unless --cwd overrides.
    project = find_project_root(args.cwd)
    if args.cwd == os.getcwd() and project.root != Path(args.cwd).resolve():
        # Only auto-anchor when the user didn't pass --cwd explicitly.
        args.cwd = str(project.root)

    # Fold any project-level config defaults into args.
    _apply_project_config(args, project)

    session = _initial_session(args, project)

    console = make_console()
    bind_tools(session.cwd)
    _register_sdk_tools()  # makes <tool_call> available across the SDK

    from .. import list_skills

    if args.task:
        # Non-interactive single-task mode — pipes-friendly.
        from ._background import shutdown_manager
        from ._loop import run_turn

        try:
            run_turn(console, session, args.task)
        finally:
            shutdown_manager()
        return 0

    # Show a banner that includes the project info.
    try:
        show_banner(
            console, session, skill_count=len(list_skills()),
            project=project,
        )
        repl(console, session)
    except KeyboardInterrupt:
        from ._background import shutdown_manager

        shutdown_manager()
        console.print("\n[brand]bye.[/brand]")
    return 0


def main_or_subcommand(argv: list[str] | None = None) -> int:
    """Top-level dispatcher for the `essarion` console entry.

    - `essarion`                  → interactive agent REPL
    - `essarion init [<path>]`    → create `.essarion/` skeleton
    - `essarion --task "..."`     → one-shot task
    - `essarion --resume <id>`    → resume a saved session
    - `essarion <subcommand>`     → existing CLI subcommands (skills,
       providers, workflows, version, estimate, reason, generate)

    Subcommand detection: if the first positional looks like a known CLI
    subcommand, we hand off; otherwise we treat the args as agent args.
    """
    argv = sys.argv[1:] if argv is None else list(argv)

    # `essarion init` is owned by the agent module.
    if argv and argv[0] == "init":
        return cmd_init(argv[1:])

    # Known subcommands from the existing CLI. Imported lazily so the agent
    # path doesn't pay for it.
    from ..cli import build_parser as _build_existing_parser

    existing = _build_existing_parser()
    subcommand_names: set[str] = set()
    for a in existing._actions:
        if isinstance(a, argparse._SubParsersAction):
            subcommand_names.update(a.choices.keys())

    if argv and argv[0] in subcommand_names:
        from ..cli import main as _cli_main

        return _cli_main(argv)

    return run_agent(argv)
