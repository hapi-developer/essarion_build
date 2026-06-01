"""Tests for the code-intelligence slash commands: /map /outline /symbol."""

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
    c._buf = buf
    return c


@pytest.fixture
def session(tmp_path: Path) -> Session:
    (tmp_path / "svc.py").write_text(
        "def handler():\n    return compute()\n\ndef compute():\n    return 1\n"
    )
    return Session(
        id=new_session_id(), cwd=str(tmp_path),
        provider="openrouter", model="openai/gpt-4o-mini", budget_usd=1.0,
    )


def _out(c: Console) -> str:
    return c._buf.getvalue()


def test_map_command(console, session) -> None:
    dispatch(console, session, "/map")
    out = _out(console)
    assert "repo map" in out and "svc.py" in out


def test_outline_command(console, session) -> None:
    dispatch(console, session, "/outline svc.py")
    out = _out(console)
    assert "handler" in out and "compute" in out


def test_outline_without_arg_shows_usage(console, session) -> None:
    dispatch(console, session, "/outline")
    assert "usage" in _out(console)


def test_symbol_command(console, session) -> None:
    dispatch(console, session, "/symbol compute")
    out = _out(console)
    assert "definition" in out and "svc.py:" in out


def test_symbol_without_arg_shows_usage(console, session) -> None:
    dispatch(console, session, "/symbol")
    assert "usage" in _out(console)
