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
