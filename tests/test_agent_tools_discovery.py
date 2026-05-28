"""Tests for the new discovery tools: find_files + glob."""

from __future__ import annotations

from pathlib import Path

from essarion_build.agent import _tools


def _seed(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text("# auth")
    (tmp_path / "src" / "billing.py").write_text("# billing")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_auth.py").write_text("# test")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.py").write_text("# noisy")


def test_find_files_matches_name(tmp_path: Path) -> None:
    _seed(tmp_path)
    _tools.bind_tools(tmp_path)
    out = _tools.find_files("auth.py")
    assert "src/auth.py" in out
    assert "billing.py" not in out


def test_find_files_skips_node_modules(tmp_path: Path) -> None:
    _seed(tmp_path)
    _tools.bind_tools(tmp_path)
    out = _tools.find_files("*.py")
    assert "ignored.py" not in out


def test_find_files_no_matches(tmp_path: Path) -> None:
    _seed(tmp_path)
    _tools.bind_tools(tmp_path)
    assert _tools.find_files("*.rs") == "(no matches)"


def test_glob_recursive(tmp_path: Path) -> None:
    _seed(tmp_path)
    _tools.bind_tools(tmp_path)
    out = _tools.glob("src/**/*.py")
    assert "src/auth.py" in out
    assert "src/billing.py" in out


def test_glob_top_level(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hi")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("x")
    _tools.bind_tools(tmp_path)
    out = _tools.glob("*.md")
    assert "README.md" in out
    assert "x.py" not in out
