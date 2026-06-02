"""Post-edit diagnostics — run an auto-detected, zero-config checker on a file
the agent just edited and feed real problems back, the way Cline/Roo surface the
editor's "problems" panel. This extends the standard-library syntax gate (which
only asks "does it parse?") with whatever fast checker is already installed:
undefined names, unused imports, real lint — so the agent fixes them in the
*same* step instead of finding out at test time.

Zero configuration, on by default. We only use checkers that:

* run on a **single file with no project setup** (so they can't spew config
  errors at someone who never asked for a linter), and
* are **read-only static analysers** (never execute the edited code), and
* are **auto-detected on PATH** (cached) — nothing installed → nothing happens,
  the syntax gate still runs.

Turn it off with `[verify] lint_on_edit = false` in `.essarion/config.toml` or
the `ESSARION_NO_LINT_ON_EDIT` environment variable. Nothing else to set up.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

# extension → ordered checkers; the first one present on PATH wins. Each is
# (binary, argv-builder). Every command runs standalone on one file and exits
# nonzero (printing detail) when it finds a problem.
_CHECKERS: dict[str, list[tuple[str, Callable[[Path], list[str]]]]] = {
    ".py": [
        ("ruff", lambda p: ["check", "--quiet", "--output-format", "concise", str(p)]),
        ("pyflakes", lambda p: [str(p)]),
    ],
    ".pyi": [
        ("ruff", lambda p: ["check", "--quiet", "--output-format", "concise", str(p)]),
    ],
    ".rb": [("ruby", lambda p: ["-c", str(p)])],
    ".php": [("php", lambda p: ["-l", str(p)])],
    ".sh": [("shellcheck", lambda p: ["--format", "gcc", str(p)])],
    ".bash": [("shellcheck", lambda p: ["--format", "gcc", str(p)])],
    ".lua": [("luacheck", lambda p: ["--no-color", "--codes", str(p)])],
}

_WHICH_CACHE: dict[str, str | None] = {}


def _which(binary: str) -> str | None:
    if binary not in _WHICH_CACHE:
        _WHICH_CACHE[binary] = shutil.which(binary)
    return _WHICH_CACHE[binary]


def _env_off() -> bool:
    return os.environ.get("ESSARION_NO_LINT_ON_EDIT", "").strip().lower() not in {"", "0", "false", "no"}


# Default on. `configure()` (called from bind_tools) refreshes this from the
# project config / env so a real session reflects the user's preference, with
# zero config required to get the default-on behaviour.
LINT_ON_EDIT: bool = not _env_off()


def configure(root: str | Path) -> None:
    """Refresh the default-on toggle from the env and the project config."""
    global LINT_ON_EDIT
    if _env_off():
        LINT_ON_EDIT = False
        return
    try:
        from ._project import find_project_root, load_project_config

        verify = load_project_config(find_project_root(root)).get("verify") or {}
        LINT_ON_EDIT = verify.get("lint_on_edit", True) is not False
    except Exception:  # noqa: BLE001 - config must never break a turn
        LINT_ON_EDIT = True


def available_checker(path: str | Path) -> str | None:
    """Name of the checker that would run for `path`, or None — for messaging."""
    for binary, _ in _CHECKERS.get(Path(path).suffix.lower(), []):
        if _which(binary):
            return binary
    return None


def diagnose(path: str | Path, *, root: str | Path | None = None,
             timeout: int = 10, max_lines: int = 8) -> str:
    """Run the first available standalone checker on `path`; return a concise
    diagnostic note to append to the edit result, or "" if it's clean / no
    checker is installed / anything goes wrong. Never raises, never blocks long."""
    path = Path(path)
    checkers = _CHECKERS.get(path.suffix.lower())
    if not checkers:
        return ""
    for binary, build in checkers:
        exe = _which(binary)
        if not exe:
            continue
        try:
            proc = subprocess.run(
                [exe, *build(path)], capture_output=True, text=True,
                timeout=timeout, cwd=str(root or path.parent), check=False,
            )
        except Exception:  # noqa: BLE001 - missing/odd tool → stay silent
            return ""
        if proc.returncode == 0:
            return ""  # ran clean
        body = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if not body:
            return ""
        return _format(binary, path, body, max_lines)
    return ""


def _format(tool: str, path: Path, body: str, max_lines: int) -> str:
    base = path.name
    abs_str = str(path.resolve())
    lines = [
        ln.replace(abs_str, base).replace(str(path), base)
        for ln in body.splitlines() if ln.strip()
    ]
    extra = len(lines) - max_lines
    shown = "\n  ".join(lines[:max_lines])
    note = f"⚠ {tool} flagged {base} — fix before continuing:\n  {shown}"
    if extra > 0:
        note += f"\n  … (+{extra} more)"
    return note


__all__ = ["LINT_ON_EDIT", "configure", "diagnose", "available_checker"]
