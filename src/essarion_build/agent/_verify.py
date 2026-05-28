"""Verification — run tests / linters after a change to confirm it works.

After the agent applies a code change, it's often worth running a quick
check (pytest, mypy, lint, build) to verify the change didn't break
anything. This module provides:

- `auto_detect_check(cwd)` — guess a reasonable check command from
  what's in the project (pytest if `tests/`, npm test if package.json
  with a "test" script, cargo test if Cargo.toml, etc.)
- `VerifyResult` — structured outcome (ok, exit code, head of output)
- `run_check(cmd, cwd)` — execute and capture
- `/verify` slash command (implemented in `_commands.py`)
- per-project `[verify].check_cmd` in `.essarion/config.toml` to set
  an explicit command

The check is OPT-IN: the agent doesn't auto-run unless the user has
configured `[verify].auto = true` in their `.essarion/config.toml`.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

from pydantic import BaseModel


_HEAD_LIMIT = 4000  # max chars of output to surface


class VerifyResult(BaseModel):
    """Outcome of a verification command."""

    cmd: str
    exit_code: int
    ok: bool
    output: str = ""

    @property
    def head(self) -> str:
        """First _HEAD_LIMIT chars of the captured output, truncated cleanly."""
        if len(self.output) <= _HEAD_LIMIT:
            return self.output
        return self.output[:_HEAD_LIMIT] + "\n... (truncated)"


def run_check(cmd: str, *, cwd: str | Path, timeout: int = 120) -> VerifyResult:
    """Run `cmd` under `cwd` and return a VerifyResult."""
    try:
        result = subprocess.run(
            shlex.split(cmd),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return VerifyResult(
            cmd=cmd,
            exit_code=-1,
            ok=False,
            output=f"(timed out after {timeout}s)",
        )
    except FileNotFoundError as e:
        return VerifyResult(
            cmd=cmd,
            exit_code=127,
            ok=False,
            output=f"(command not found: {e})",
        )
    output = (result.stdout or "") + (
        f"\n(stderr)\n{result.stderr}" if result.stderr else ""
    )
    return VerifyResult(
        cmd=cmd,
        exit_code=result.returncode,
        ok=result.returncode == 0,
        output=output,
    )


def auto_detect_check(cwd: str | Path) -> str | None:
    """Heuristic: pick a check command from the project's shape.

    Returns the command (a string) or None if we couldn't guess. Order
    of preference: pytest > npm test > cargo test > go test > make test.
    Per-project `.essarion/config.toml` `[verify].check_cmd` always
    wins over this heuristic (handled by the caller).
    """
    root = Path(cwd)
    # pytest: a tests/ dir AND pyproject.toml or pytest.ini
    if (root / "tests").is_dir() and (
        (root / "pyproject.toml").is_file() or (root / "pytest.ini").is_file()
    ):
        return "pytest -q --tb=short"
    # npm test
    pj = root / "package.json"
    if pj.is_file():
        try:
            data = json.loads(pj.read_text(encoding="utf-8"))
            if isinstance(data.get("scripts"), dict) and "test" in data["scripts"]:
                return "npm test --silent"
        except (OSError, json.JSONDecodeError):
            pass
    # cargo test
    if (root / "Cargo.toml").is_file():
        return "cargo test --quiet"
    # go test
    if (root / "go.mod").is_file():
        return "go test ./..."
    # Makefile target `test`
    if (root / "Makefile").is_file():
        try:
            mk = (root / "Makefile").read_text(encoding="utf-8")
            if "\ntest:" in mk or mk.startswith("test:"):
                return "make test"
        except OSError:
            pass
    return None


def configured_check(cwd: str | Path) -> tuple[str | None, bool]:
    """Read `[verify].check_cmd` and `[verify].auto` from project config.

    Returns `(cmd_or_None, auto_run_flag)`. Falls back to
    `auto_detect_check(cwd)` if the config doesn't specify a command.
    """
    from ._project import find_project_root, load_project_config

    project = find_project_root(cwd)
    cfg = load_project_config(project)
    verify_cfg = cfg.get("verify", {}) or {}
    cmd = verify_cfg.get("check_cmd")
    auto = bool(verify_cfg.get("auto", False))
    if not cmd:
        cmd = auto_detect_check(cwd)
    return cmd, auto


__all__ = [
    "VerifyResult",
    "run_check",
    "auto_detect_check",
    "configured_check",
]
