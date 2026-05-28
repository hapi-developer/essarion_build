"""Tests for the new run_turn helpers: directory autoload + missing-key UX."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from essarion_build import Context
from essarion_build.agent import _loop, _ui
from essarion_build.agent._session import Session, new_session_id
from essarion_build.agent._theme import ESSARION_THEME


@pytest.fixture
def console() -> Console:
    return Console(theme=ESSARION_THEME, file=io.StringIO(), force_terminal=False, width=120)


def test_autoload_picks_up_directory_reference(tmp_path: Path, console: Console) -> None:
    (tmp_path / "src" / "auth").mkdir(parents=True)
    (tmp_path / "src" / "auth" / "jwt.py").write_text("def verify(): pass\n")
    (tmp_path / "src" / "auth" / "session.py").write_text("class Session: pass\n")

    ctx = Context()
    loaded = _loop._autoload_files("review src/auth/ for issues", tmp_path, ctx, console)

    paths = {f.path for f in ctx.repo_files}
    assert "src/auth/jwt.py" in paths
    assert "src/auth/session.py" in paths
    assert "src/auth/jwt.py" in loaded


def test_autoload_skips_vcs_dirs(tmp_path: Path, console: Console) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / ".git").mkdir()
    (tmp_path / "src" / ".git" / "config").write_text("bogus")
    (tmp_path / "src" / "real.py").write_text("ok\n")

    ctx = Context()
    _loop._autoload_files("look at src/ please", tmp_path, ctx, console)
    paths = {f.path for f in ctx.repo_files}
    assert "src/real.py" in paths
    assert all(".git" not in p for p in paths)


def test_autoload_caps_directory_files(tmp_path: Path, console: Console) -> None:
    (tmp_path / "many").mkdir()
    for i in range(20):
        (tmp_path / "many" / f"file{i:02d}.py").write_text(f"# {i}\n")

    ctx = Context()
    loaded = _loop._autoload_files("explore many/ for patterns", tmp_path, ctx, console)

    # We cap at _DIR_AUTOLOAD_MAX (8) per dir reference.
    assert 0 < len([p for p in loaded if p.startswith("many/")]) <= _loop._DIR_AUTOLOAD_MAX


def test_autoload_dedup_between_file_and_dir(tmp_path: Path, console: Console) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# a\n")
    (tmp_path / "src" / "b.py").write_text("# b\n")

    ctx = Context()
    _loop._autoload_files(
        "review src/a.py and the src/ folder", tmp_path, ctx, console
    )
    paths = [f.path for f in ctx.repo_files]
    # `a.py` should appear once even though it matched both regexes.
    assert paths.count("src/a.py") == 1


def test_missing_api_key_shows_friendly_message(
    monkeypatch, console: Console, tmp_path: Path
) -> None:
    """When the underlying provider raises RuntimeError about a missing key,
    the agent surfaces a typed error with a /model hint."""

    def boom(name, api_key, model):
        raise RuntimeError("OPENROUTER_API_KEY is not set ...")

    monkeypatch.setattr("essarion_build.agent._loop.build_provider", boom)
    session = Session(
        id=new_session_id(),
        cwd=str(tmp_path),
        provider="openrouter",
        model="openai/gpt-4o-mini",
        budget_usd=1.00,
    )
    monkeypatch.setattr(_ui, "prompt_approve_plan", lambda c: "cancel")
    monkeypatch.setattr(_ui, "prompt_approve_apply", lambda c, kind="code": "discard")

    _loop.run_turn(console, session, "anything")
    out = console.file.getvalue()
    assert "missing API key" in out
    assert "OPENROUTER_API_KEY" in out
    # The friendly hint to /model is also shown.
    assert "/model" in out
