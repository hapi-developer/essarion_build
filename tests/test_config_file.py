"""Tests for the optional TOML config-file loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from essarion_build._config import DEFAULT_MODEL, DEFAULT_PROVIDER, current
from essarion_build._config_file import load_config_file, starter_skills


@pytest.fixture(autouse=True)
def _reset_config():
    """Restore module defaults around each test."""
    from essarion_build._config import configure

    snapshot = current().model_copy(deep=True)
    yield
    configure(
        provider=snapshot.provider,
        runtime=snapshot.runtime,
        api_key=snapshot.api_key,
        model=snapshot.model,
        max_tokens=snapshot.max_tokens,
    )


def test_load_config_file_applies_defaults(tmp_path) -> None:
    cfg = tmp_path / "essarion.toml"
    cfg.write_text(
        """
[defaults]
provider = "anthropic"
model = "claude-sonnet-4-6"
max_tokens = 3000
        """.strip()
    )
    parsed, used = load_config_file(cfg)
    assert used == cfg
    assert parsed["defaults"]["provider"] == "anthropic"
    c = current()
    assert c.provider == "anthropic"
    assert c.model == "claude-sonnet-4-6"
    assert c.max_tokens == 3000


def test_load_config_file_no_path_no_op(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # No essarion.toml exists; user-config dir doesn't either in tmp_path.
    monkeypatch.setenv("HOME", str(tmp_path))
    parsed, used = load_config_file()
    assert used is None
    assert parsed == {}
    # Module defaults unchanged.
    assert current().provider == DEFAULT_PROVIDER
    assert current().model == DEFAULT_MODEL


def test_load_config_file_partial_section(tmp_path) -> None:
    """A config with only `model` set leaves other defaults untouched."""
    cfg = tmp_path / "essarion.toml"
    cfg.write_text('[defaults]\nmodel = "openai/gpt-4o"\n')
    load_config_file(cfg)
    assert current().model == "openai/gpt-4o"
    assert current().provider == DEFAULT_PROVIDER


def test_starter_skills_reads_list() -> None:
    parsed = {
        "defaults": {
            "skills": {"enabled": ["secure_coding", "testing"]}
        }
    }
    assert starter_skills(parsed) == ["secure_coding", "testing"]


def test_starter_skills_missing_returns_empty() -> None:
    assert starter_skills({}) == []
    assert starter_skills({"defaults": {}}) == []
    assert starter_skills({"defaults": {"skills": {}}}) == []


def test_load_config_file_picks_project_over_user(tmp_path, monkeypatch) -> None:
    """Project-scoped essarion.toml wins over ~/.config/essarion/config.toml."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    # User config: provider=openai
    user_dir = tmp_path / ".config" / "essarion"
    user_dir.mkdir(parents=True)
    (user_dir / "config.toml").write_text('[defaults]\nprovider = "openai"\n')

    # Project config: provider=gemini
    (tmp_path / "essarion.toml").write_text('[defaults]\nprovider = "gemini"\n')

    parsed, used = load_config_file()
    # `Path("essarion.toml")` resolves to a relative path; check the name.
    assert used is not None
    assert used.name == "essarion.toml"
    assert current().provider == "gemini"
