"""Built-in tools the agent can use.

These map onto the SDK's `essarion_build.tools.register_tool` surface
(so the `<tool_call name=…>…</tool_call>` mechanism can drive them) AND
are exposed for direct use by the agent's REPL when it needs to do file
I/O on the user's behalf.

Every tool here is **sandboxed** to the session's CWD (no path traversal
outside of it) and emits a structured record the UI can render and the
session can persist.

Side-effect tools (write_file, apply_diff, run_shell) are gated by
require_approval=True so the agent calls them with a confirmation hook;
read tools (read_file, list_dir, grep) run freely.
"""

from __future__ import annotations

import fnmatch
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .. import tools as sdk_tools
from . import _background, _changes, _hooks


# Resolved per-session by the REPL via `bind_tools(cwd, ...)`. Keeping
# this module-level so the SDK's tool registry can call functions that
# already know their sandbox root without us threading state through
# every call site.
_SANDBOX_ROOT: Path = Path.cwd()
_AUTO_APPROVE: bool = False


def bind_tools(cwd: str | Path, *, auto_approve: bool = False) -> None:
    """Configure the sandbox root and the background-task manager.

    Called once per REPL session, plus whenever the user runs `/cd`.
    """
    global _SANDBOX_ROOT, _AUTO_APPROVE
    _SANDBOX_ROOT = Path(cwd).resolve()
    _AUTO_APPROVE = bool(auto_approve)
    _background.bind_manager(_SANDBOX_ROOT)
    _changes.bind_changelog(_SANDBOX_ROOT)
    _hooks.bind_hooks(_SANDBOX_ROOT)


def _resolve(path: str) -> Path:
    """Resolve `path` against the sandbox root, refusing traversal."""
    p = (_SANDBOX_ROOT / path).resolve()
    if _SANDBOX_ROOT not in p.parents and p != _SANDBOX_ROOT:
        raise PermissionError(
            f"path {path!r} resolves outside the sandbox ({_SANDBOX_ROOT})"
        )
    return p


class ToolRun(BaseModel):
    """One tool invocation record — what the agent did, displayed in the UI."""

    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    ok: bool = True
    result: str = ""
    error: str = ""


# ---------- read-only tools ----------

def read_file(path: str, max_bytes: int = 64 * 1024) -> str:
    """Read a UTF-8 file under the sandbox root. Truncated if huge."""
    p = _resolve(path)
    if not p.is_file():
        raise FileNotFoundError(f"not a file: {path}")
    data = p.read_text(encoding="utf-8", errors="replace")
    if len(data) > max_bytes:
        return data[:max_bytes] + f"\n... (truncated; full size {len(data):,} bytes)"
    return data


def list_dir(path: str = ".", max_entries: int = 200) -> str:
    """List entries directly under `path` (no recursion). Returns a plain text list."""
    p = _resolve(path)
    if not p.is_dir():
        raise NotADirectoryError(f"not a directory: {path}")
    entries: list[str] = []
    for child in sorted(p.iterdir()):
        if child.name.startswith(".") and child.name not in {".gitignore", ".env.example"}:
            continue
        kind = "d" if child.is_dir() else "f"
        try:
            size = child.stat().st_size if child.is_file() else 0
        except OSError:
            size = 0
        entries.append(f"{kind} {child.name}" + (f" ({size:,}B)" if kind == "f" else ""))
        if len(entries) >= max_entries:
            entries.append("... (truncated)")
            break
    return "\n".join(entries)


def grep(pattern: str, path: str = ".", max_hits: int = 50) -> str:
    """Search files under `path` for a regex `pattern`. Returns up to max_hits hits."""
    import re

    p = _resolve(path)
    try:
        rx = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"bad regex {pattern!r}: {e}")
    hits: list[str] = []
    for f in p.rglob("*"):
        if not f.is_file():
            continue
        if any(part in {".git", "__pycache__", "node_modules", ".venv"} for part in f.parts):
            continue
        try:
            for i, line in enumerate(
                f.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
            ):
                if rx.search(line):
                    rel = f.relative_to(_SANDBOX_ROOT).as_posix()
                    hits.append(f"{rel}:{i}: {line.strip()[:200]}")
                    if len(hits) >= max_hits:
                        return "\n".join(hits) + "\n... (truncated)"
        except OSError:
            continue
    return "\n".join(hits) if hits else "(no matches)"


# ---------- discovery tools ----------

# Directory names we never recurse into for find/glob.
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".mypy_cache", ".pytest_cache"}


def find_files(pattern: str, path: str = ".", max_hits: int = 200) -> str:
    """Find files under `path` whose name matches the fnmatch `pattern`.

    Pattern matches the file *name only*, not the relative path. Use
    `glob()` if you need path-shaped patterns like `src/**/*.py`.
    """
    root = _resolve(path)
    hits: list[str] = []
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        if any(part in _SKIP_DIRS for part in f.parts):
            continue
        if fnmatch.fnmatch(f.name, pattern):
            hits.append(f.relative_to(_SANDBOX_ROOT).as_posix())
            if len(hits) >= max_hits:
                hits.append("... (truncated)")
                break
    return "\n".join(hits) if hits else "(no matches)"


def glob(pattern: str, max_hits: int = 200) -> str:
    """Path-shaped glob from the sandbox root. Supports `**` recursion.

    Examples: `src/**/*.py`, `tests/test_*.py`, `*.md`.
    """
    hits: list[str] = []
    for p in _SANDBOX_ROOT.glob(pattern):
        if not p.is_file():
            continue
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        hits.append(p.relative_to(_SANDBOX_ROOT).as_posix())
        if len(hits) >= max_hits:
            hits.append("... (truncated)")
            break
    return "\n".join(hits) if hits else "(no matches)"


# ---------- side-effect tools ----------

def write_file(path: str, content: str) -> str:
    """Write `content` to `path` (relative to sandbox). Creates parent dirs.

    Records the prior content in the session change log so the user can
    `/undo` to revert and `/diff` to inspect.
    """
    p = _resolve(path)
    _hooks.before_tool("write_file", {"path": path})
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        _changes.current_changelog().record(
            path, after=content, sandbox_root=_SANDBOX_ROOT
        )
    except Exception:  # noqa: BLE001 - changelog must never block a write
        pass
    p.write_text(content, encoding="utf-8")
    return _hooks.after_tool("write_file", {"path": path}, f"wrote {len(content):,} bytes to {path}")


def apply_diff(path: str, old: str, new: str) -> str:
    """Replace the *unique* occurrence of `old` with `new` in `path`.

    Refuses if `old` doesn't appear or appears more than once — this is
    the same safety the SDK's Edit tool surface uses. The full new file
    is recorded in the change log for `/undo`.
    """
    p = _resolve(path)
    if not p.is_file():
        raise FileNotFoundError(f"not a file: {path}")
    _hooks.before_tool("apply_diff", {"path": path})
    body = p.read_text(encoding="utf-8")
    count = body.count(old)
    if count == 0:
        raise ValueError(f"old text not found in {path}")
    if count > 1:
        raise ValueError(
            f"old text appears {count} times in {path}; tighten the snippet"
        )
    new_body = body.replace(old, new)
    try:
        _changes.current_changelog().record(
            path, after=new_body, sandbox_root=_SANDBOX_ROOT
        )
    except Exception:  # noqa: BLE001
        pass
    p.write_text(new_body, encoding="utf-8")
    return _hooks.after_tool("apply_diff", {"path": path}, f"applied 1-occurrence patch to {path}")


def delete_file(path: str) -> str:
    """Delete a file under the sandbox root.

    The prior content is recorded in the change log so the user can `/undo`
    to restore it. Refuses anything that isn't a regular file (no recursive
    directory removal — that's a footgun the agent shouldn't have).
    """
    p = _resolve(path)
    if not p.is_file():
        raise FileNotFoundError(f"not a file: {path}")
    _hooks.before_tool("delete_file", {"path": path})
    try:
        _changes.current_changelog().record_delete(path, sandbox_root=_SANDBOX_ROOT)
    except Exception:  # noqa: BLE001 - changelog must never block the delete
        pass
    p.unlink()
    return _hooks.after_tool("delete_file", {"path": path}, f"deleted {path}")


def run_shell(cmd: str, timeout: int = 30) -> str:
    """Run a shell command in the sandbox root, blocking until exit.

    Runs through a real shell so the operators models reach for — redirection
    (`>`), pipes (`|`), `&&`/`;`, globs, `$VARS` — work as written. Prefers bash
    when present, falls back to the system shell.

    For long-running commands (dev servers, test suites, installs) use
    `start_background` instead — it returns immediately with a task id.
    """
    import shutil

    _hooks.before_tool("run_shell", {"command": cmd})
    shell_exe = shutil.which("bash") or None  # None → subprocess uses /bin/sh
    try:
        result = subprocess.run(
            cmd,
            cwd=_SANDBOX_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=True,
            executable=shell_exe,
        )
    except subprocess.TimeoutExpired:
        return f"(timed out after {timeout}s)"
    except FileNotFoundError as e:
        return f"(command not found: {e})"
    out = (result.stdout or "") + (
        f"\n(stderr)\n{result.stderr}" if result.stderr else ""
    )
    out += f"\n[exit {result.returncode}]"
    if len(out) > 8000:
        out = out[:8000] + "\n... (truncated)"
    return _hooks.after_tool("run_shell", {"command": cmd}, out)


# ---------- background tools ----------

def start_background(cmd: str, name: str | None = None, detached: bool = False) -> str:
    """Spawn a background task running `cmd` from the sandbox root.

    Returns the task id (short hex). Use `check_background(id)` to poll,
    `wait_background(id)` to block, `kill_background(id)` to terminate.

    `detached=True` keeps the process alive after the agent exits — useful
    for dev servers you want to keep running.
    """
    mgr = _background.current_manager()
    task = mgr.start(cmd, name=name, detached=detached)
    return (
        f"started task [{task.id}] '{task.name}' (pid={task.pid})"
        if task.is_running
        else f"task [{task.id}] failed to start: {task.status}"
    )


def check_background(task_id: str, tail: int = 30) -> str:
    """Status + recent output of a background task."""
    mgr = _background.current_manager()
    try:
        task = mgr.poll(task_id)
    except KeyError:
        return f"unknown task: {task_id}"
    body = mgr.tail(task_id, lines=tail)
    head = (
        f"[{task.id}] {task.name}  status={task.status}"
        + (f" exit={task.exit_code}" if task.exit_code is not None else "")
        + f"  elapsed={task.elapsed_seconds:.1f}s"
    )
    return head + ("\n" + body if body.strip() else "")


def wait_background(task_id: str, timeout_seconds: float = 60.0) -> str:
    """Block until the task finishes or `timeout_seconds` elapse."""
    mgr = _background.current_manager()
    try:
        task = mgr.wait(task_id, timeout=timeout_seconds)
    except KeyError:
        return f"unknown task: {task_id}"
    if task.is_running:
        return f"[{task.id}] still running after {timeout_seconds:.1f}s"
    return f"[{task.id}] {task.status} (exit {task.exit_code}) in {task.elapsed_seconds:.1f}s"


def kill_background(task_id: str) -> str:
    """Terminate a running background task."""
    mgr = _background.current_manager()
    try:
        task = mgr.kill(task_id)
    except KeyError:
        return f"unknown task: {task_id}"
    return f"[{task.id}] killed (exit {task.exit_code})"


def list_background() -> str:
    """List every known task with status."""
    mgr = _background.current_manager()
    tasks = mgr.poll_all()
    if not tasks:
        return "(no background tasks)"
    lines = []
    for t in tasks:
        suffix = f" exit={t.exit_code}" if t.exit_code is not None else ""
        lines.append(f"[{t.id}] {t.status:<7} {t.name[:50]}  {t.elapsed_seconds:.1f}s{suffix}")
    return "\n".join(lines)


# Tools that require user approval before running.
SIDE_EFFECT_TOOLS = {
    "write_file", "apply_diff", "delete_file", "run_shell",
    "start_background", "kill_background",
}


def register_all() -> None:
    """Register every built-in tool with the SDK's tool registry so the
    `<tool_call>` mechanism can drive them too."""
    sdk_tools.register_tool("read_file", description="read a file from disk")(read_file)
    sdk_tools.register_tool("list_dir", description="list a directory's entries")(list_dir)
    sdk_tools.register_tool("grep", description="search files for a regex")(grep)
    sdk_tools.register_tool("find_files", description="find files by fnmatch name pattern")(find_files)
    sdk_tools.register_tool("glob", description="path-shaped glob from the sandbox root")(glob)
    sdk_tools.register_tool("write_file", description="write a file")(write_file)
    sdk_tools.register_tool("apply_diff", description="replace a unique snippet in a file")(apply_diff)
    sdk_tools.register_tool("delete_file", description="delete a file (undoable)")(delete_file)
    sdk_tools.register_tool("run_shell", description="run a shell command (blocking)")(run_shell)
    sdk_tools.register_tool("start_background", description="start a background task; returns id")(start_background)
    sdk_tools.register_tool("check_background", description="status + recent output of a task")(check_background)
    sdk_tools.register_tool("wait_background", description="block until a task finishes")(wait_background)
    sdk_tools.register_tool("kill_background", description="terminate a background task")(kill_background)
    sdk_tools.register_tool("list_background", description="list every background task")(list_background)
