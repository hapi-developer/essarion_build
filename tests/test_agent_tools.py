"""Tests for the agent's sandboxed tool surface."""

from __future__ import annotations

import pytest

from essarion_build.agent import _tools


def test_read_file_within_sandbox(tmp_path) -> None:
    (tmp_path / "a.py").write_text("print(1)\n")
    _tools.bind_tools(tmp_path)
    assert _tools.read_file("a.py").strip() == "print(1)"


def test_read_file_traversal_blocked(tmp_path) -> None:
    _tools.bind_tools(tmp_path)
    with pytest.raises(PermissionError):
        _tools.read_file("../../etc/passwd")


def test_list_dir_skips_hidden(tmp_path) -> None:
    (tmp_path / "visible.py").write_text("x")
    (tmp_path / ".secret").write_text("s")
    _tools.bind_tools(tmp_path)
    out = _tools.list_dir(".")
    assert "visible.py" in out
    assert ".secret" not in out


def test_list_dir_keeps_gitignore_exception(tmp_path) -> None:
    (tmp_path / ".gitignore").write_text("*.tmp")
    _tools.bind_tools(tmp_path)
    out = _tools.list_dir(".")
    assert ".gitignore" in out


def test_grep_finds_matches(tmp_path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    pass\n")
    (tmp_path / "b.py").write_text("def bar():\n    return foo()\n")
    _tools.bind_tools(tmp_path)
    out = _tools.grep(r"foo")
    assert "a.py:1" in out
    assert "b.py:2" in out


def test_grep_skips_vcs_dirs(tmp_path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("foo")
    (tmp_path / "a.py").write_text("foo")
    _tools.bind_tools(tmp_path)
    out = _tools.grep(r"foo")
    assert "a.py" in out
    assert ".git" not in out


def test_write_file_creates_parent_dirs(tmp_path) -> None:
    _tools.bind_tools(tmp_path)
    _tools.write_file("sub/dir/new.py", "x = 1\n")
    assert (tmp_path / "sub" / "dir" / "new.py").read_text() == "x = 1\n"


def test_apply_diff_unique_occurrence(tmp_path) -> None:
    (tmp_path / "f.py").write_text("a = 1\nb = 2\n")
    _tools.bind_tools(tmp_path)
    _tools.apply_diff("f.py", "b = 2", "b = 99")
    assert (tmp_path / "f.py").read_text() == "a = 1\nb = 99\n"


def test_apply_diff_refuses_missing(tmp_path) -> None:
    (tmp_path / "f.py").write_text("a = 1\n")
    _tools.bind_tools(tmp_path)
    with pytest.raises(ValueError):
        _tools.apply_diff("f.py", "missing", "x")


def test_apply_diff_refuses_ambiguous(tmp_path) -> None:
    (tmp_path / "f.py").write_text("x\nx\n")
    _tools.bind_tools(tmp_path)
    with pytest.raises(ValueError):
        _tools.apply_diff("f.py", "x", "y")


def test_run_shell_captures_output(tmp_path) -> None:
    _tools.bind_tools(tmp_path)
    out = _tools.run_shell("echo hello")
    assert "hello" in out
    assert "[exit 0]" in out


def test_run_shell_timeout(tmp_path) -> None:
    _tools.bind_tools(tmp_path)
    out = _tools.run_shell("sleep 5", timeout=1)
    assert "timed out" in out


def test_register_all_wires_sdk_tools() -> None:
    """All built-in agent tools are registered with the SDK's tool surface."""
    from essarion_build import tools as sdk_tools

    _tools.register_all()
    names = {t.name for t in sdk_tools.list_tools()}
    for required in {"read_file", "list_dir", "grep", "write_file", "apply_diff", "run_shell"}:
        assert required in names
