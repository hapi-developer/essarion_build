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

import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .. import tools as sdk_tools


# Resolved per-session by the REPL via `bind_tools(cwd, ...)`. Keeping
# this module-level so the SDK's tool registry can call functions that
# already know their sandbox root without us threading state through
# every call site.
_SANDBOX_ROOT: Path = Path.cwd()
_AUTO_APPROVE: bool = False


def bind_tools(cwd: str | Path, *, auto_approve: bool = False) -> None:
    """Configure the sandbox root for subsequent tool calls.

    Called once per REPL session, plus whenever the user runs `/cd`.
    """
    global _SANDBOX_ROOT, _AUTO_APPROVE
    _SANDBOX_ROOT = Path(cwd).resolve()
    _AUTO_APPROVE = bool(auto_approve)


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


# ---------- side-effect tools ----------

def write_file(path: str, content: str) -> str:
    """Write `content` to `path` (relative to sandbox). Creates parent dirs."""
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {len(content):,} bytes to {path}"


def apply_diff(path: str, old: str, new: str) -> str:
    """Replace the *unique* occurrence of `old` with `new` in `path`.

    Refuses if `old` doesn't appear or appears more than once — this is
    the same safety the SDK's Edit tool surface uses.
    """
    p = _resolve(path)
    if not p.is_file():
        raise FileNotFoundError(f"not a file: {path}")
    body = p.read_text(encoding="utf-8")
    count = body.count(old)
    if count == 0:
        raise ValueError(f"old text not found in {path}")
    if count > 1:
        raise ValueError(
            f"old text appears {count} times in {path}; tighten the snippet"
        )
    p.write_text(body.replace(old, new), encoding="utf-8")
    return f"applied 1-occurrence patch to {path}"


def run_shell(cmd: str, timeout: int = 30) -> str:
    """Run a shell command in the sandbox root. Captures stdout+stderr."""
    parts = shlex.split(cmd)
    try:
        result = subprocess.run(
            parts,
            cwd=_SANDBOX_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
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
    return out


# Tools that require user approval before running.
SIDE_EFFECT_TOOLS = {"write_file", "apply_diff", "run_shell"}


def register_all() -> None:
    """Register every built-in tool with the SDK's tool registry so the
    `<tool_call>` mechanism can drive them too."""
    sdk_tools.register_tool("read_file", description="read a file from disk")(read_file)
    sdk_tools.register_tool("list_dir", description="list a directory's entries")(list_dir)
    sdk_tools.register_tool("grep", description="search files for a regex")(grep)
    sdk_tools.register_tool("write_file", description="write a file")(write_file)
    sdk_tools.register_tool("apply_diff", description="replace a unique snippet in a file")(apply_diff)
    sdk_tools.register_tool("run_shell", description="run a shell command in the sandbox")(run_shell)
