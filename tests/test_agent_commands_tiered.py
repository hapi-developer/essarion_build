"""Tests for the tiered-model + credential-recovery commands:
/triage, /reload, and the credential check on /model."""

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
        id=new_session_id(), cwd=str(tmp_path),
        provider="openrouter", model="openai/gpt-4o", budget_usd=1.0,
    )
    bind_tools(tmp_path)
    return s


def _out(c: Console) -> str:
    return c._buf.getvalue()


def test_triage_set_and_clear(console, session) -> None:
    dispatch(console, session, "/triage openai/gpt-4o-mini")
    assert session.triage_model == "openai/gpt-4o-mini"
    assert "auto-triage routing" in _out(console)
    dispatch(console, session, "/triage off")
    assert session.triage_model is None


def test_triage_show_when_unset(console, session) -> None:
    dispatch(console, session, "/triage")
    assert "no triage model" in _out(console)


def test_model_switch_warns_on_missing_key(console, session, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    dispatch(console, session, "/model openai/gpt-4o")
    out = _out(console)
    assert "model set to openai/gpt-4o" in out
    assert "OPENAI_API_KEY" in out  # told which key the route needs


def test_model_switch_quiet_when_key_present(console, session, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    dispatch(console, session, "/model anthropic/claude-sonnet-4-6")
    out = _out(console)
    assert "model set to anthropic" in out
    assert "heads up" not in out  # key present → no warning


def test_reload_reads_dotenv(console, session, tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (tmp_path / ".env").write_text(
        '# creds\nexport OPENAI_API_KEY="sk-from-dotenv"\nFOO=bar\n', encoding="utf-8"
    )
    dispatch(console, session, "/reload")
    import os

    assert os.environ.get("OPENAI_API_KEY") == "sk-from-dotenv"
    assert os.environ.get("FOO") == "bar"
    out = _out(console)
    assert "reloaded" in out
    assert "OPENAI_API_KEY" in out
    # values are never printed.
    assert "sk-from-dotenv" not in out


def test_reload_no_dotenv(console, session) -> None:
    dispatch(console, session, "/reload")
    assert "no .env file found" in _out(console)
