"""Tests for the session change log + /diff / /undo helpers."""

from __future__ import annotations

from pathlib import Path

from essarion_build.agent._changes import (
    ChangeLog,
    bind_changelog,
    current_changelog,
    reset_changelog,
)
from essarion_build.agent import _tools


def test_record_create(tmp_path: Path) -> None:
    log = ChangeLog(cwd=str(tmp_path))
    entry = log.record("new.py", after="print(1)\n", sandbox_root=tmp_path)
    assert entry.kind == "create"
    assert entry.before is None
    assert entry.after == "print(1)\n"


def test_record_modify(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("a = 1\n")
    log = ChangeLog(cwd=str(tmp_path))
    entry = log.record("f.py", after="a = 2\n", sandbox_root=tmp_path)
    assert entry.kind == "modify"
    assert entry.before == "a = 1\n"
    assert entry.after == "a = 2\n"


def test_diff_collapses_multiple_edits_to_same_file(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("a = 1\n")
    log = ChangeLog(cwd=str(tmp_path))
    log.record("f.py", after="a = 2\n", sandbox_root=tmp_path)
    (tmp_path / "f.py").write_text("a = 2\n")  # actually write to disk so the second
                                                  # `before` comes from disk
    log.record("f.py", after="a = 3\n", sandbox_root=tmp_path)
    diff = log.diff()
    # Net change is 1 → 3.
    assert "-a = 1" in diff
    assert "+a = 3" in diff
    # The intermediate "+a = 2" / "-a = 2" should not appear in the collapsed diff.
    assert "-a = 2" not in diff
    assert "+a = 2" not in diff


def test_undo_create_deletes_file(tmp_path: Path) -> None:
    log = ChangeLog(cwd=str(tmp_path))
    f = tmp_path / "new.py"
    log.record("new.py", after="x = 1\n", sandbox_root=tmp_path)
    f.write_text("x = 1\n")
    entry = log.undo_last(sandbox_root=tmp_path)
    assert entry is not None
    assert entry.kind == "create"
    assert not f.exists()


def test_undo_modify_restores_previous_content(tmp_path: Path) -> None:
    f = tmp_path / "f.py"
    f.write_text("old\n")
    log = ChangeLog(cwd=str(tmp_path))
    log.record("f.py", after="new\n", sandbox_root=tmp_path)
    f.write_text("new\n")
    log.undo_last(sandbox_root=tmp_path)
    assert f.read_text() == "old\n"


def test_undo_empty_log_returns_none(tmp_path: Path) -> None:
    log = ChangeLog(cwd=str(tmp_path))
    assert log.undo_last(sandbox_root=tmp_path) is None


def test_files_touched_dedups(tmp_path: Path) -> None:
    log = ChangeLog(cwd=str(tmp_path))
    log.record("a.py", after="1", sandbox_root=tmp_path)
    log.record("b.py", after="2", sandbox_root=tmp_path)
    log.record("a.py", after="3", sandbox_root=tmp_path)
    assert log.files_touched() == ["a.py", "b.py"]


def test_write_file_records_in_changelog(tmp_path: Path) -> None:
    _tools.bind_tools(tmp_path)
    reset_changelog()
    _tools.write_file("new.py", "x = 1\n")
    log = current_changelog()
    assert log.files_touched() == ["new.py"]
    assert log.entries[0].kind == "create"


def test_apply_diff_records_in_changelog(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("a = 1\nb = 2\n")
    _tools.bind_tools(tmp_path)
    reset_changelog()
    _tools.apply_diff("f.py", "b = 2", "b = 99")
    log = current_changelog()
    assert log.entries
    # The net change is captured as a modify.
    assert log.entries[0].kind == "modify"
    assert "b = 99" in log.entries[0].after
