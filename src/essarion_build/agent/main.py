"""Agent entry point. Called by the `essarion` console script when no
existing CLI subcommand is given."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .._config import current
from ._loop import repl
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


def _initial_session(args: argparse.Namespace) -> Session:
    """Build the Session object the REPL will mutate."""
    if args.resume:
        s = load_session(args.resume)
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

    cfg = current()
    return Session(
        id=new_session_id(),
        cwd=str(Path(args.cwd).resolve()),
        provider=args.provider or cfg.provider,
        model=args.model or cfg.model,
        escalate_model=args.escalate or None,
        max_tokens=args.max_tokens or cfg.max_tokens,
        budget_usd=args.budget,
        skills_mode=args.skills,
    )


def run_agent(argv: list[str] | None = None) -> int:
    """Entry point invoked when the user types `essarion` (no subcommand).

    Returns an int suitable for sys.exit().
    """
    parser = build_agent_parser()
    args = parser.parse_args(argv)
    session = _initial_session(args)

    console = make_console()
    bind_tools(session.cwd)
    _register_sdk_tools()  # makes <tool_call> available across the SDK

    from .. import list_skills

    if args.task:
        # Non-interactive single-task mode — pipes-friendly.
        from ._loop import run_turn

        run_turn(console, session, args.task)
        return 0

    try:
        show_banner(console, session, skill_count=len(list_skills()))
        repl(console, session)
    except KeyboardInterrupt:
        console.print("\n[brand]bye.[/brand]")
    return 0


def main_or_subcommand(argv: list[str] | None = None) -> int:
    """Top-level dispatcher for the `essarion` console entry.

    - `essarion`                  → interactive agent REPL
    - `essarion --task "..."`     → one-shot task
    - `essarion --resume <id>`    → resume a saved session
    - `essarion <subcommand>`     → existing CLI subcommands (skills,
       providers, workflows, version, estimate, reason, generate)

    Subcommand detection: if the first positional looks like a known CLI
    subcommand, we hand off; otherwise we treat the args as agent args.
    """
    argv = sys.argv[1:] if argv is None else list(argv)

    # Known subcommands from the existing CLI. Imported lazily so the agent
    # path doesn't pay for it.
    from ..cli import build_parser as _build_existing_parser

    existing = _build_existing_parser()
    existing_actions = {
        a.dest for a in existing._actions if isinstance(a, argparse._SubParsersAction)
    }
    subcommand_names: set[str] = set()
    for a in existing._actions:
        if isinstance(a, argparse._SubParsersAction):
            subcommand_names.update(a.choices.keys())

    if argv and argv[0] in subcommand_names:
        from ..cli import main as _cli_main

        return _cli_main(argv)

    return run_agent(argv)
