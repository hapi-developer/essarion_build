"""Tests for project root detection + `essarion init`."""

from __future__ import annotations

from pathlib import Path

import pytest

from essarion_build.agent._project import (
    find_project_root,
    init_project,
    load_project_config,
)


def test_find_project_root_uses_essarion_dir(tmp_path: Path) -> None:
    (tmp_path / ".essarion").mkdir()
    nested = tmp_path / "src" / "a"
    nested.mkdir(parents=True)
    project = find_project_root(nested)
    assert project.root == tmp_path
    assert project.detected_by == ".essarion"


def test_find_project_root_falls_back_to_git(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "src" / "a"
    nested.mkdir(parents=True)
    project = find_project_root(nested)
    assert project.root == tmp_path
    assert project.detected_by == ".git"


def test_find_project_root_falls_back_to_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    nested = tmp_path / "src" / "a"
    nested.mkdir(parents=True)
    project = find_project_root(nested)
    assert project.root == tmp_path
    assert project.detected_by == "pyproject.toml"


def test_find_project_root_falls_back_to_package_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}")
    project = find_project_root(tmp_path)
    assert project.root == tmp_path
    assert project.detected_by == "package.json"


def test_find_project_root_no_markers_returns_cwd(tmp_path: Path) -> None:
    project = find_project_root(tmp_path)
    assert project.root == tmp_path
    assert project.detected_by == ""


def test_essarion_wins_over_git_at_same_level(tmp_path: Path) -> None:
    """When both .essarion/ and .git/ are siblings at the same dir, .essarion wins."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".essarion").mkdir()
    project = find_project_root(tmp_path)
    assert project.detected_by == ".essarion"


def test_init_creates_essarion_dir_with_starter_files(tmp_path: Path) -> None:
    project = init_project(tmp_path)
    assert project.root == tmp_path
    assert (tmp_path / ".essarion").is_dir()
    assert (tmp_path / ".essarion" / "config.toml").is_file()
    assert (tmp_path / ".essarion" / "sessions").is_dir()
    assert (tmp_path / ".essarion" / ".gitignore").is_file()


def test_init_is_idempotent_no_clobber(tmp_path: Path) -> None:
    """Re-running init does not overwrite an existing config."""
    project = init_project(tmp_path)
    cfg = project.essarion_dir / "config.toml"
    cfg.write_text("# my custom config\n[defaults]\nprovider = 'anthropic'\n")
    init_project(tmp_path)
    body = cfg.read_text()
    assert "my custom config" in body
    assert "anthropic" in body


def test_init_refuses_non_directory(tmp_path: Path) -> None:
    f = tmp_path / "not-a-dir"
    f.write_text("hi")
    with pytest.raises(NotADirectoryError):
        init_project(f)


def test_project_sessions_dir_per_project(tmp_path: Path) -> None:
    """When .essarion/ exists, sessions go in `<root>/.essarion/sessions/`."""
    project = init_project(tmp_path)
    sd = project.sessions_dir
    assert sd == project.essarion_dir / "sessions"


def test_project_sessions_dir_global_fallback(tmp_path: Path, monkeypatch) -> None:
    """No .essarion/ → fall back to ~/.essarion/sessions/."""
    monkeypatch.setenv("HOME", str(tmp_path))
    project = find_project_root(tmp_path)  # no markers
    sd = project.sessions_dir
    assert tmp_path / ".essarion" / "sessions" == sd


def test_load_project_config_reads_defaults(tmp_path: Path) -> None:
    project = init_project(tmp_path)
    project.config_path.write_text(
        '[defaults]\nprovider = "anthropic"\nmodel = "claude-sonnet-4-6"\n'
    ) if project.config_path else None
    # init wrote a starter; overwrite with real content
    (project.essarion_dir / "config.toml").write_text(
        '[defaults]\nprovider = "anthropic"\nmodel = "claude-sonnet-4-6"\n'
    )
    data = load_project_config(project)
    assert data["defaults"]["provider"] == "anthropic"
    assert data["defaults"]["model"] == "claude-sonnet-4-6"


def test_load_project_config_returns_empty_when_missing(tmp_path: Path) -> None:
    project = find_project_root(tmp_path)  # no .essarion/
    data = load_project_config(project)
    assert data == {}
