"""Regression tests for bugs found in the codebase audit.

Each test pins a specific defect that previously slipped past the suite because
it lived in an untested code path.
"""

from __future__ import annotations

import tokenize
from pathlib import Path

import pytest


# --- glob() must honour the sandbox boundary like every other file tool -------

def test_glob_does_not_escape_the_sandbox(tmp_path: Path) -> None:
    from essarion_build.agent import _tools

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "inside.txt").write_text("ok", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("leak", encoding="utf-8")

    original_root = _tools._SANDBOX_ROOT
    try:
        _tools.bind_tools(sandbox)
        # A normal in-sandbox glob still works.
        assert "inside.txt" in _tools.glob("*.txt")
        # A traversal pattern must NOT reach the sibling file outside the root.
        escaped = _tools.glob("../*.txt")
        assert "secret.txt" not in escaped
        assert escaped == "(no matches)"
        # Deep traversal to an absolute system path is likewise blocked.
        assert _tools.glob("../../../../../../etc/*") == "(no matches)"
    finally:
        _tools.bind_tools(original_root)


# --- desktop teardown import must resolve ------------------------------------

def test_unregister_desktop_tools_is_exported() -> None:
    """`stop_desktop_session()` does `from ..computer import unregister_desktop_tools`;
    that name must be re-exported from the package or teardown raises ImportError."""
    from essarion_build import computer

    assert hasattr(computer, "unregister_desktop_tools")
    assert hasattr(computer, "unregister_computer_tools")
    assert "unregister_desktop_tools" in computer.__all__
    # The agent glue imports it lazily inside stop_desktop_session — exercise that.
    from essarion_build.computer import unregister_desktop_tools  # noqa: F401


# --- validator must survive a tokenization failure ---------------------------

def test_validate_python_survives_tokenize_error(monkeypatch) -> None:
    """The comment scan catches `tokenize.TokenError` (not the non-existent
    `tokenize.TokenizeError`, which would raise AttributeError from the handler)."""
    from essarion_build import validators

    def _raise(_readline):
        raise tokenize.TokenError("unexpected EOF")

    monkeypatch.setattr(tokenize, "generate_tokens", _raise)
    # Must not raise — the malformed-token case is swallowed, not re-raised.
    issues = validators.validate_python("x = 1\n")
    assert isinstance(issues, list)


# --- config file must apply the `effort` default -----------------------------

def test_config_file_applies_effort_default(tmp_path, monkeypatch) -> None:
    from essarion_build import _config, _config_file

    snap = _config.current().model_copy(deep=True)
    try:
        cfg = tmp_path / "essarion.toml"
        cfg.write_text('[defaults]\nprovider = "stub"\neffort = "deep"\n', encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        _config_file.load_config_file()
        assert _config.current().effort == "deep"
    finally:
        # Don't leak the stub/deep config into other tests (no global reset).
        _config.configure(
            provider=snap.provider, runtime=snap.runtime, api_key=snap.api_key,
            model=snap.model, triage_model=snap.triage_model,
            max_tokens=snap.max_tokens, effort=snap.effort,
        )
