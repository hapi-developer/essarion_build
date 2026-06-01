"""Tests for the top-level `essarion` dispatcher (subcommand vs agent)."""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from essarion_build.agent import main as agent_main


def test_main_dispatches_known_subcommand_to_existing_cli(capsys, monkeypatch) -> None:
    """`essarion version` falls through to the existing cli.main(['version'])."""
    rc = agent_main.main_or_subcommand(["version"])
    out = capsys.readouterr().out.strip()
    from essarion_build import __version__

    assert rc == 0
    assert out == __version__


def test_main_dispatches_skills_subcommand(capsys) -> None:
    rc = agent_main.main_or_subcommand(["skills"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "secure_coding" in out


def test_main_dispatches_providers_subcommand(capsys) -> None:
    rc = agent_main.main_or_subcommand(["providers"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "openrouter" in out


def test_main_runs_agent_non_interactive_with_task_arg(
    monkeypatch, capsys, tmp_path
) -> None:
    """`essarion --task "..."` runs one turn without entering the REPL."""
    # Patch run_turn so we don't need a real provider for this test.
    called: dict[str, str] = {}

    def fake_run_turn(console, session, task):
        called["task"] = task
        called["model"] = session.model

    monkeypatch.setattr("essarion_build.agent._loop.run_turn", fake_run_turn)

    rc = agent_main.run_agent(
        [
            "--task",
            "review src/auth.py",
            "--cwd",
            str(tmp_path),
            "--provider",
            "stub",
            "--model",
            "stub-model",
        ]
    )
    assert rc == 0
    assert called["task"] == "review src/auth.py"
    assert called["model"] == "stub-model"


def test_task_text_joins_multiword_task_flag() -> None:
    """`--task please code a website` (unquoted) is joined, not truncated to
    'please' — the exact bug from 0.3.1."""
    parser = agent_main.build_agent_parser()
    ns = parser.parse_args(["--task", "please", "code", "a", "website"])
    assert agent_main._task_text(ns) == "please code a website"


def test_task_text_joins_bare_positional_words() -> None:
    """`essarion fix the failing test` runs one-shot with no --task, no quotes."""
    parser = agent_main.build_agent_parser()
    ns = parser.parse_args(["fix", "the", "failing", "test"])
    assert agent_main._task_text(ns) == "fix the failing test"


def test_no_task_means_repl() -> None:
    parser = agent_main.build_agent_parser()
    assert agent_main._task_text(parser.parse_args([])) == ""


def test_bare_invocation_opens_the_repl(monkeypatch, tmp_path) -> None:
    """Bare `essarion` / `essarion-build` (no task) launches the chat REPL."""
    opened: dict[str, bool] = {}
    monkeypatch.setattr(agent_main, "repl", lambda console, session: opened.setdefault("repl", True))
    monkeypatch.setattr(agent_main, "show_banner", lambda *a, **k: None)
    rc = agent_main.run_agent(["--cwd", str(tmp_path), "--provider", "stub", "--model", "m"])
    assert rc == 0
    assert opened.get("repl") is True


def test_essarion_build_bare_routes_to_repl(monkeypatch, tmp_path) -> None:
    """The unified dispatcher (what the `essarion-build` script now calls) opens
    the REPL when given no subcommand."""
    opened: dict[str, bool] = {}
    monkeypatch.setattr(agent_main, "repl", lambda console, session: opened.setdefault("repl", True))
    monkeypatch.setattr(agent_main, "show_banner", lambda *a, **k: None)
    monkeypatch.chdir(tmp_path)
    rc = agent_main.main_or_subcommand([])
    assert rc == 0
    assert opened.get("repl") is True


def test_cmd_init_creates_skeleton(tmp_path, capsys) -> None:
    """`essarion init <path>` creates the .essarion/ skeleton."""
    rc = agent_main.cmd_init([str(tmp_path)])
    assert rc == 0
    assert (tmp_path / ".essarion" / "config.toml").is_file()
    assert (tmp_path / ".essarion" / "sessions").is_dir()


def test_cmd_init_seeds_memory(tmp_path) -> None:
    """`essarion init <path> --with-memory FACT` seeds memory.md."""
    rc = agent_main.cmd_init(
        [str(tmp_path), "--with-memory", "Use snake_case",
         "--with-memory", "Tests in tests/"]
    )
    assert rc == 0
    body = (tmp_path / ".essarion" / "memory.md").read_text()
    assert "Use snake_case" in body
    assert "Tests in tests/" in body


def test_main_resume_loads_prior_session(monkeypatch, tmp_path) -> None:
    """`essarion --resume <id>` reads ~/.essarion/sessions/<id>.json."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from essarion_build.agent._session import (
        Session,
        TaskTurn,
        new_session_id,
        save_session,
    )

    sid = new_session_id()
    prior = Session(
        id=sid,
        cwd=str(tmp_path),
        provider="openrouter",
        model="openai/gpt-4o-mini",
        history=[TaskTurn(task="earlier task")],
    )
    save_session(prior)

    # Patch run_turn so resume completes without a network call.
    captured: dict = {}

    def fake_run_turn(console, session, task):
        captured["session_id"] = session.id
        captured["history_len"] = len(session.history)

    monkeypatch.setattr("essarion_build.agent._loop.run_turn", fake_run_turn)

    agent_main.run_agent(
        ["--task", "next task", "--resume", sid, "--cwd", str(tmp_path)]
    )
    assert captured["session_id"] == sid
    assert captured["history_len"] == 1  # the prior turn is preserved
