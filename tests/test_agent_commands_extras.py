"""Tests for the new slash commands added in v0.3.0."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from essarion_build.agent._commands import dispatch
from essarion_build.agent._session import Session, new_session_id
from essarion_build.agent._theme import ESSARION_THEME
from essarion_build.agent._tools import bind_tools


@pytest.fixture
def console() -> Console:
    buf = io.StringIO()
    c = Console(theme=ESSARION_THEME, file=buf, force_terminal=False, width=120)
    c._buf = buf
    return c


@pytest.fixture
def session(tmp_path: Path) -> Session:
    s = Session(
        id=new_session_id(),
        cwd=str(tmp_path),
        provider="openrouter",
        model="openai/gpt-4o-mini",
        budget_usd=1.00,
    )
    bind_tools(tmp_path)
    return s


def _out(console: Console) -> str:
    return console._buf.getvalue()


def test_remember_no_args_shows_memory(console, session) -> None:
    dispatch(console, session, "/remember")
    out = _out(console)
    assert "no remembered facts" in out or "project memory" in out


def test_remember_with_arg_adds_and_persists(console, session, tmp_path) -> None:
    from essarion_build.agent._project import init_project

    init_project(tmp_path)
    dispatch(console, session, "/remember use snake_case everywhere")
    out = _out(console)
    assert "remembered" in out
    # Reload and check it persisted.
    from essarion_build.agent._memory import load_memory

    mem = load_memory(tmp_path)
    assert any("snake_case" in f for f in mem.facts)


def test_forget_removes_fact(console, session, tmp_path) -> None:
    from essarion_build.agent._memory import load_memory
    from essarion_build.agent._project import init_project

    init_project(tmp_path)
    mem = load_memory(tmp_path)
    mem.add_fact("first fact")
    mem.add_fact("second fact")
    mem.save()
    dispatch(console, session, "/forget first")
    reloaded = load_memory(tmp_path)
    assert not any("first" in f for f in reloaded.facts)
    assert any("second" in f for f in reloaded.facts)


def test_verify_runs_command(console, session) -> None:
    dispatch(console, session, "/verify true")
    out = _out(console)
    assert "PASS" in out


def test_verify_fail_shows_fail(console, session) -> None:
    dispatch(console, session, "/verify false")
    assert "FAIL" in _out(console)


def test_verify_no_command_errors(console, session) -> None:
    dispatch(console, session, "/verify")
    out = _out(console)
    assert "no verify command" in out or "FAIL" in out  # depends on auto-detect


def test_diff_empty_when_no_changes(console, session) -> None:
    from essarion_build.agent._changes import reset_changelog

    reset_changelog()
    dispatch(console, session, "/diff")
    assert "no changes" in _out(console)


def test_diff_shows_changes(console, session, tmp_path) -> None:
    from essarion_build.agent._changes import reset_changelog
    from essarion_build.agent._tools import write_file

    reset_changelog()
    write_file("new.py", "x = 1\n")
    dispatch(console, session, "/diff")
    out = _out(console)
    assert "new.py" in out


def test_undo_reverts_last_change(console, session, tmp_path) -> None:
    from essarion_build.agent._changes import reset_changelog
    from essarion_build.agent._tools import write_file

    reset_changelog()
    write_file("new.py", "x = 1\n")
    assert (tmp_path / "new.py").is_file()
    dispatch(console, session, "/undo")
    assert not (tmp_path / "new.py").is_file()


def test_undo_no_changes_says_nothing_to_undo(console, session) -> None:
    from essarion_build.agent._changes import reset_changelog

    reset_changelog()
    dispatch(console, session, "/undo")
    assert "nothing to undo" in _out(console)


def test_unknown_slash_command_shows_error(console, session) -> None:
    dispatch(console, session, "/not-a-real-command")
    assert "unknown command" in _out(console).lower()


def test_custom_slash_command_from_essarion_dir(console, session, tmp_path) -> None:
    """Files under .essarion/commands/<name>.md become /<name> slash commands."""
    from essarion_build.agent._project import init_project

    init_project(tmp_path)
    cmd_dir = tmp_path / ".essarion" / "commands"
    cmd_dir.mkdir()
    (cmd_dir / "tldr.md").write_text("Summarize {args} in one paragraph.")

    captured: dict = {}

    # Patch run_turn so we don't make a model call.
    import essarion_build.agent._commands as cmds
    original = cmds.dispatch

    def fake_run_turn(c, s, task):
        captured["task"] = task

    import essarion_build.agent._loop as loop
    monkey_target = "essarion_build.agent._loop.run_turn"
    orig_run_turn = loop.run_turn
    loop.run_turn = fake_run_turn
    try:
        dispatch(console, session, "/tldr the auth module")
    finally:
        loop.run_turn = orig_run_turn
    assert "Summarize the auth module" in captured["task"]


def test_workflow_shortcuts_route_correctly(console, session, monkeypatch) -> None:
    captured: dict = {}

    def fake_run_turn(c, s, task):
        captured["task"] = task

    import essarion_build.agent._loop as loop
    monkeypatch.setattr(loop, "run_turn", fake_run_turn)
    dispatch(console, session, "/review src/auth.py")
    assert captured["task"].startswith("review: ")
    assert "src/auth.py" in captured["task"]

    dispatch(console, session, "/fix payment hangs")
    assert captured["task"].startswith("fix-bug: ")


def test_help_lists_new_commands(console, session) -> None:
    dispatch(console, session, "/help")
    out = _out(console)
    for cmd in ["/remember", "/forget", "/verify", "/diff", "/undo",
                 "/commit", "/ask", "/subagent", "/review", "/fix"]:
        assert cmd in out
