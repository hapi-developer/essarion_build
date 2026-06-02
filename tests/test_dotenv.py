"""`.env` made easy: zero-dep loader, startup auto-load semantics, /keys set."""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from rich.console import Console

from essarion_build.agent._commands import dispatch
from essarion_build.agent._dotenv import (
    default_env_paths,
    load_dotenv_files,
    parse_dotenv,
    upsert_dotenv,
)
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
    s = Session(id=new_session_id(), cwd=str(tmp_path), provider="openrouter", model="m")
    bind_tools(tmp_path)
    return s


def _out(c: Console) -> str:
    return c._buf.getvalue()


# ---- parser ----

def test_parse_handles_comments_export_and_quotes() -> None:
    kv = parse_dotenv('# c\nexport A="1"\nB=2\n  C = \'x y\' \nnoequals\n')
    assert kv == {"A": "1", "B": "2", "C": "x y"}


def test_load_non_override_lets_shell_win(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("K_DEMO=fromfile\n")
    monkeypatch.setenv("K_DEMO", "fromshell")
    load_dotenv_files([tmp_path / ".env"], override=False)
    assert os.environ["K_DEMO"] == "fromshell"
    load_dotenv_files([tmp_path / ".env"], override=True)
    assert os.environ["K_DEMO"] == "fromfile"


def test_load_sets_unset_keys(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("K_UNSET", raising=False)
    (tmp_path / ".env").write_text("K_UNSET=v\n")
    got = load_dotenv_files([tmp_path / ".env"], override=False)
    assert os.environ.get("K_UNSET") == "v"
    assert got == ["K_UNSET"]


def test_default_env_paths_orders_project_then_cwd(tmp_path) -> None:
    root = tmp_path / "proj"
    sub = root / "pkg"
    sub.mkdir(parents=True)
    paths = default_env_paths(sub, root)
    assert paths == [root / ".env", sub / ".env"]


def test_upsert_updates_in_place(tmp_path) -> None:
    p = tmp_path / ".env"
    upsert_dotenv(p, "X", "1")
    upsert_dotenv(p, "X", "2")
    upsert_dotenv(p, "Y", "3")
    text = p.read_text()
    assert "X=2" in text and "Y=3" in text
    assert text.count("X=") == 1  # updated, not duplicated


# ---- /keys set ----

def test_keys_set_inline_sets_env_without_echoing_value(console, session, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    dispatch(console, session, "/keys set openai sk-secret-123")
    assert os.environ.get("OPENAI_API_KEY") == "sk-secret-123"
    out = _out(console)
    assert "OPENAI_API_KEY set" in out
    assert "sk-secret-123" not in out  # value never printed


def test_keys_set_save_persists_and_warns_untracked(console, session, tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    dispatch(console, session, "/keys set openrouter sk-or-xyz save")
    assert os.environ.get("OPENROUTER_API_KEY") == "sk-or-xyz"
    env_file = tmp_path / ".env"
    assert "OPENROUTER_API_KEY=sk-or-xyz" in env_file.read_text()
    out = _out(console)
    assert "saved OPENROUTER_API_KEY" in out
    assert "gitignore" in out  # no .gitignore → warned


def test_keys_set_gitignored_no_warning(console, session, tmp_path, monkeypatch) -> None:
    (tmp_path / ".gitignore").write_text(".env\n")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    dispatch(console, session, "/keys set openai sk-1 save")
    assert "isn't in .gitignore" not in _out(console)


def test_keys_set_unknown_provider(console, session) -> None:
    dispatch(console, session, "/keys set bogus sk-x")
    assert "unknown provider" in _out(console)
