"""Tests for /cost, /whoami, and the categorized /help output."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from essarion_build import Usage
from essarion_build.agent._commands import COMMANDS, dispatch
from essarion_build.agent._session import Session, TaskTurn, new_session_id
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


def test_cost_empty_session(console, session) -> None:
    dispatch(console, session, "/cost")
    assert "no turns" in _out(console)


def test_cost_after_turns_shows_ledger(console, session) -> None:
    session.record(TaskTurn(
        task="design something",
        usage=Usage(prompt_tokens=100, completion_tokens=20, total_tokens=120),
        cost_usd=0.0123,
    ))
    session.record(TaskTurn(
        task="write the code",
        usage=Usage(prompt_tokens=200, completion_tokens=40, total_tokens=240),
        cost_usd=0.0234,
    ))
    dispatch(console, session, "/cost")
    out = _out(console)
    assert "design something" in out
    assert "write the code" in out
    assert "120" in out
    assert "240" in out


def test_cost_with_path_estimates(console, session, tmp_path) -> None:
    (tmp_path / "a.py").write_text("print(1)\n" * 100)
    dispatch(console, session, "/cost a.py")
    out = _out(console)
    assert "a.py" in out
    assert "tokens" in out


def test_cost_path_not_found(console, session) -> None:
    dispatch(console, session, "/cost not_a_real_path.py")
    assert "not a file" in _out(console)


def test_whoami_shows_session_info(console, session) -> None:
    dispatch(console, session, "/whoami")
    out = _out(console)
    assert session.id in out
    # Either "project" or "cwd" appears.
    assert "project" in out or "cwd" in out
    assert "openai/gpt-4o-mini" in out
    assert "essarion" in out


def test_help_organized_into_groups(console, session) -> None:
    dispatch(console, session, "/help")
    out = _out(console)
    # Spot-check group labels show up.
    assert "session" in out
    assert "workflows" in out
    assert "background" in out
    # And actual commands appear under them.
    assert "/whoami" in out
    assert "/review" in out
    assert "/bg" in out


def test_help_filter_narrows_results(console, session) -> None:
    dispatch(console, session, "/help cost")
    out = _out(console)
    assert "/cost" in out
    # Commands NOT matching shouldn't appear in the filtered output.
    assert "/yolo" not in out


def test_every_command_categorized_or_in_misc(console, session) -> None:
    """The /help impl should reach every command in COMMANDS (no silent drops)."""
    dispatch(console, session, "/help")
    out = _out(console)
    for cmd in COMMANDS:
        assert cmd in out, f"command {cmd} missing from /help"
