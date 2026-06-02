"""Tests for the post-edit diagnostics runner (`agent/_diagnostics.py`)."""

from __future__ import annotations

import shutil

import pytest

from essarion_build.agent import _diagnostics, _tools

_HAS_RUFF = shutil.which("ruff") is not None
ruff_only = pytest.mark.skipif(not _HAS_RUFF, reason="ruff not installed")


@ruff_only
def test_diagnose_flags_real_lint_issue(tmp_path):
    f = tmp_path / "bad.py"
    f.write_text("import os\n")  # unused import → ruff F401
    note = _diagnostics.diagnose(f, root=tmp_path)
    assert note
    assert "ruff" in note
    assert "F401" in note or "unused" in note
    assert "bad.py" in note  # path reduced to basename


@ruff_only
def test_diagnose_clean_file_is_silent(tmp_path):
    f = tmp_path / "ok.py"
    f.write_text("def f():\n    return 1\n")
    assert _diagnostics.diagnose(f, root=tmp_path) == ""


def test_diagnose_unknown_extension_is_silent(tmp_path):
    f = tmp_path / "data.bin"
    f.write_text("x")
    assert _diagnostics.diagnose(f, root=tmp_path) == ""


def test_diagnose_graceful_when_no_checker_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(_diagnostics, "_which", lambda _b: None)
    f = tmp_path / "x.py"
    f.write_text("import os\n")
    assert _diagnostics.diagnose(f, root=tmp_path) == ""


def test_configure_respects_env_off(tmp_path, monkeypatch):
    monkeypatch.setenv("ESSARION_NO_LINT_ON_EDIT", "1")
    _diagnostics.configure(tmp_path)
    assert _diagnostics.LINT_ON_EDIT is False


def test_configure_default_on(tmp_path, monkeypatch):
    monkeypatch.delenv("ESSARION_NO_LINT_ON_EDIT", raising=False)
    _diagnostics.configure(tmp_path)
    assert _diagnostics.LINT_ON_EDIT is True


def test_configure_disabled_by_project_config(tmp_path, monkeypatch):
    monkeypatch.delenv("ESSARION_NO_LINT_ON_EDIT", raising=False)
    ess = tmp_path / ".essarion"
    ess.mkdir()
    (ess / "config.toml").write_text("[verify]\nlint_on_edit = false\n")
    _diagnostics.configure(tmp_path)
    assert _diagnostics.LINT_ON_EDIT is False


@ruff_only
def test_write_file_appends_lint_diagnostics(tmp_path, monkeypatch):
    _tools.bind_tools(tmp_path)
    # bind_tools → configure() set it off (suite env); force on for this test.
    monkeypatch.setattr(_diagnostics, "LINT_ON_EDIT", True)
    out = _tools.write_file("svc.py", "import os\n\ndef f():\n    return 1\n")
    assert "⚠" in out and "ruff" in out


@ruff_only
def test_write_file_clean_has_no_lint_note(tmp_path, monkeypatch):
    _tools.bind_tools(tmp_path)
    monkeypatch.setattr(_diagnostics, "LINT_ON_EDIT", True)
    out = _tools.write_file("svc.py", "def f():\n    return 1\n")
    assert "⚠" not in out
