"""Tests for slash commands."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from essarion_build.agent._commands import dispatch
from essarion_build.agent._session import Session, new_session_id
from essarion_build.agent._theme import ESSARION_THEME


@pytest.fixture
def console() -> Console:
    buf = io.StringIO()
    c = Console(theme=ESSARION_THEME, file=buf, force_terminal=False, width=120)
    c._buf = buf  # attach for assertions
    return c


@pytest.fixture
def session(tmp_path: Path) -> Session:
    return Session(
        id=new_session_id(),
        cwd=str(tmp_path),
        provider="openrouter",
        model="openai/gpt-4o-mini",
        budget_usd=1.00,
    )


def _output(console: Console) -> str:
    return console._buf.getvalue()


def test_dispatch_returns_none_for_non_slash(console, session) -> None:
    assert dispatch(console, session, "hello") is None


def test_quit(console, session) -> None:
    assert dispatch(console, session, "/quit") == "quit"


def test_unknown_command_shows_error(console, session) -> None:
    result = dispatch(console, session, "/bogus")
    assert result == "continue"
    assert "unknown command" in _output(console).lower()


def test_help_lists_known_commands(console, session) -> None:
    dispatch(console, session, "/help")
    out = _output(console)
    for cmd in ["/help", "/quit", "/clear", "/budget", "/model", "/skills", "/cd"]:
        assert cmd in out


def test_budget_sets_and_shows(console, session) -> None:
    dispatch(console, session, "/budget 5.50")
    assert session.budget_usd == 5.50
    dispatch(console, session, "/budget")
    assert "$0.0000" in _output(console)


def test_model_changes_session(console, session) -> None:
    dispatch(console, session, "/model anthropic/claude-sonnet-4-6")
    assert session.provider == "anthropic"
    assert session.model == "claude-sonnet-4-6"


def test_model_unknown_provider_errors(console, session) -> None:
    dispatch(console, session, "/model whatever/foo")
    out = _output(console)
    assert "unknown provider" in out.lower()
    # Session untouched.
    assert session.provider == "openrouter"


def test_escalate_set_and_clear(console, session) -> None:
    dispatch(console, session, "/escalate claude-sonnet-4-6")
    assert session.escalate_model == "claude-sonnet-4-6"
    dispatch(console, session, "/escalate off")
    assert session.escalate_model is None


def test_skills_mode_switch(console, session) -> None:
    dispatch(console, session, "/skills all")
    assert session.skills_mode == "all"
    dispatch(console, session, "/skills none")
    assert session.skills_mode == "none"


def test_cd_changes_cwd(console, session, tmp_path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    dispatch(console, session, f"/cd {sub}")
    assert Path(session.cwd) == sub.resolve()


def test_cd_to_nonexistent_errors(console, session, tmp_path) -> None:
    bogus = tmp_path / "nope"
    dispatch(console, session, f"/cd {bogus}")
    out = _output(console)
    assert "not a directory" in out.lower()
    # Session unchanged.
    assert Path(session.cwd) != bogus


def test_save_persists_session(console, session, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    dispatch(console, session, "/save")
    assert (tmp_path / ".essarion" / "sessions" / f"{session.id}.json").exists()


def test_pwd(console, session) -> None:
    dispatch(console, session, "/pwd")
    assert session.cwd in _output(console)


def test_yolo_toggles(console, session) -> None:
    from essarion_build.agent import _tools

    before = _tools._AUTO_APPROVE
    dispatch(console, session, "/yolo")
    assert _tools._AUTO_APPROVE != before
    # Restore for hygiene.
    dispatch(console, session, "/yolo")


def test_version(console, session) -> None:
    dispatch(console, session, "/version")
    out = _output(console)
    from essarion_build import __version__

    assert __version__ in out
