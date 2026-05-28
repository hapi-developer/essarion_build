"""Tests for /lint and did-you-mean."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from essarion_build.agent._commands import _did_you_mean, dispatch
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
    )
    bind_tools(tmp_path)
    return s


def _out(console: Console) -> str:
    return console._buf.getvalue()


def test_did_you_mean_typo_returns_closest() -> None:
    assert _did_you_mean("/budgt") == "/budget"
    assert _did_you_mean("/verfy") == "/verify"
    assert _did_you_mean("/remembar") == "/remember"


def test_did_you_mean_far_off_returns_none() -> None:
    assert _did_you_mean("/totally-not-a-real-thing-xyz") is None


def test_dispatch_shows_suggestion_for_typo(console, session) -> None:
    dispatch(console, session, "/verfy")
    assert "did you mean" in _out(console)
    assert "/verify" in _out(console)


def test_dispatch_falls_back_to_help_hint_for_unknown(console, session) -> None:
    dispatch(console, session, "/totally-not-a-real-thing-zzz")
    out = _out(console)
    assert "unknown command" in out
    assert "/help" in out
    assert "did you mean" not in out


def test_lint_no_files_warns(console, session) -> None:
    from essarion_build.agent._changes import reset_changelog

    reset_changelog()
    dispatch(console, session, "/lint")
    assert "no files to lint" in _out(console)


def test_lint_with_path_arg_runs(console, session, tmp_path) -> None:
    """Smoke: /lint <path> attempts to run a linter (or falls back)."""
    (tmp_path / "ok.py").write_text("x = 1\n")
    dispatch(console, session, "/lint ok.py")
    out = _out(console)
    # We accept any outcome — CLEAN, ISSUES, or fall-back — as long as
    # the command didn't crash.
    assert "running" in out or "no linter" in out or "lint" in out.lower()
