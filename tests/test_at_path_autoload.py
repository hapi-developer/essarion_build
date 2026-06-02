"""Inline `@path` file referencing at the prompt (Gemini-style)."""

from __future__ import annotations

import io
from pathlib import Path

from rich.console import Console

from essarion_build import Context
from essarion_build.agent import _loop
from essarion_build.agent._theme import ESSARION_THEME


def _console() -> Console:
    return Console(theme=ESSARION_THEME, file=io.StringIO(), force_terminal=False, width=120)


def test_at_path_attaches_file(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text("def login():\n    pass\n")
    ctx = Context()
    loaded = _loop._autoload_files("please review @src/auth.py for bugs", tmp_path, ctx, _console())
    assert "src/auth.py" in loaded
    assert any(f.path == "src/auth.py" for f in ctx.repo_files)


def test_at_path_attaches_extensionless_file(tmp_path: Path) -> None:
    """`@Makefile` works even though the bare-path regex requires an extension."""
    (tmp_path / "Makefile").write_text("all:\n\techo hi\n")
    ctx = Context()
    loaded = _loop._autoload_files("what does @Makefile do?", tmp_path, ctx, _console())
    assert "Makefile" in loaded


def test_at_path_attaches_directory(tmp_path: Path) -> None:
    d = tmp_path / "pkg"
    d.mkdir()
    (d / "a.py").write_text("a = 1\n")
    (d / "b.py").write_text("b = 2\n")
    ctx = Context()
    loaded = _loop._autoload_files("summarize @pkg/", tmp_path, ctx, _console())
    assert "pkg/a.py" in loaded and "pkg/b.py" in loaded


def test_at_path_ignores_email_addresses(tmp_path: Path) -> None:
    ctx = Context()
    loaded = _loop._autoload_files("ping me at user@example.com when done", tmp_path, ctx, _console())
    assert loaded == []


def test_at_path_dedups_with_bare_path(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("x = 1\n")
    ctx = Context()
    loaded = _loop._autoload_files("look at @x.py and also x.py", tmp_path, ctx, _console())
    assert loaded.count("x.py") == 1
