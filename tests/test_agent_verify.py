"""Tests for the verification helper."""

from __future__ import annotations

from pathlib import Path

from essarion_build.agent._project import init_project
from essarion_build.agent._verify import (
    auto_detect_check,
    configured_check,
    run_check,
)


def test_run_check_pass(tmp_path: Path) -> None:
    result = run_check("true", cwd=tmp_path)
    assert result.ok
    assert result.exit_code == 0


def test_run_check_fail(tmp_path: Path) -> None:
    result = run_check("false", cwd=tmp_path)
    assert not result.ok
    assert result.exit_code == 1


def test_run_check_timeout(tmp_path: Path) -> None:
    result = run_check("sleep 5", cwd=tmp_path, timeout=1)
    assert not result.ok
    assert result.exit_code == -1
    assert "timed out" in result.output


def test_run_check_unknown_command(tmp_path: Path) -> None:
    result = run_check("definitely-not-a-real-cmd-xyz", cwd=tmp_path)
    assert not result.ok
    assert result.exit_code == 127


def test_run_check_captures_stdout_and_stderr(tmp_path: Path) -> None:
    result = run_check("bash -c \"echo out; echo err >&2\"", cwd=tmp_path)
    assert "out" in result.output
    assert "err" in result.output


def test_auto_detect_pytest(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "tests").mkdir()
    cmd = auto_detect_check(tmp_path)
    assert cmd is not None
    assert "pytest" in cmd


def test_auto_detect_npm(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"scripts": {"test": "jest"}}')
    cmd = auto_detect_check(tmp_path)
    assert cmd is not None
    assert "npm test" in cmd


def test_auto_detect_npm_without_test_script_skipped(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "x"}')
    assert auto_detect_check(tmp_path) is None


def test_auto_detect_cargo(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n")
    cmd = auto_detect_check(tmp_path)
    assert cmd is not None
    assert "cargo test" in cmd


def test_auto_detect_go(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module x\n")
    cmd = auto_detect_check(tmp_path)
    assert cmd is not None
    assert "go test" in cmd


def test_auto_detect_unknown_returns_none(tmp_path: Path) -> None:
    assert auto_detect_check(tmp_path) is None


def test_configured_check_reads_config(tmp_path: Path) -> None:
    init_project(tmp_path)
    cfg = tmp_path / ".essarion" / "config.toml"
    cfg.write_text(
        "[verify]\ncheck_cmd = \"pytest -x\"\nauto = true\n"
    )
    cmd, auto = configured_check(tmp_path)
    assert cmd == "pytest -x"
    assert auto is True


def test_configured_check_falls_back_to_autodetect(tmp_path: Path) -> None:
    init_project(tmp_path)
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n")
    cmd, auto = configured_check(tmp_path)
    assert cmd is not None
    assert "cargo test" in cmd
    assert auto is False
