"""Tests for inline tool execution during the plan phase."""

from __future__ import annotations

from pathlib import Path

from essarion_build import Context
from essarion_build.agent import _inline_tools, _tools


def test_has_tool_calls_detects() -> None:
    assert _inline_tools.has_tool_calls(
        'pre <tool_call name="read_file">{"path":"a.py"}</tool_call> post'
    )
    assert not _inline_tools.has_tool_calls("just plain text")


def test_applied_results_runs_allowed_tools(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("# hello\n")
    _tools.bind_tools(tmp_path)
    _tools.register_all()

    text = '<tool_call name="read_file">{"path":"a.py"}</tool_call>'
    out = _inline_tools.applied_results(text)
    assert "<tool_result" in out
    assert "hello" in out


def test_applied_results_blocks_disallowed_inline(tmp_path: Path) -> None:
    """write_file is a side-effect tool — not in the inline allow-list."""
    _tools.bind_tools(tmp_path)
    _tools.register_all()

    text = '<tool_call name="write_file">{"path":"x","content":"y"}</tool_call>'
    out = _inline_tools.applied_results(text)
    assert 'error="true"' in out
    assert "not in allow-list" in out


def test_tool_results_summary_extracts_bodies() -> None:
    text = (
        '<tool_result name="read_file">file body here</tool_result>'
        '<tool_result name="grep">match line</tool_result>'
    )
    out = _inline_tools.tool_results_summary(text)
    assert ("read_file", "file body here") in out
    assert ("grep", "match line") in out


def test_fold_into_context_adds_notes() -> None:
    ctx = Context()
    n = _inline_tools.fold_into_context(
        ctx, [("read_file", "file body"), ("grep", "")]  # blank skipped
    )
    assert n == 1
    assert any("file body" in note for note in ctx.notes)


def test_fold_truncates_huge_bodies() -> None:
    ctx = Context()
    _inline_tools.fold_into_context(ctx, [("read_file", "x" * 20000)])
    assert any("truncated" in note for note in ctx.notes)


def test_inline_constants_are_reasonable() -> None:
    assert "read_file" in _inline_tools._INLINE_ALLOW
    assert "grep" in _inline_tools._INLINE_ALLOW
    # No side-effect tools.
    assert "write_file" not in _inline_tools._INLINE_ALLOW
    assert "run_shell" not in _inline_tools._INLINE_ALLOW
    assert _inline_tools._MAX_TOOL_ROUNDS >= 1
