"""Track file changes the agent applied during a REPL session.

Every time the agent writes a file (via the apply step, `write_file`,
or `apply_diff`), we snapshot the prior content into the change log so
the user can `/undo` to revert and `/diff` to see what changed since
session start.

This is in-memory + ephemeral. We do NOT try to track changes made by
the user editing files outside the agent — only changes the agent
itself applied.
"""

from __future__ import annotations

import difflib
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ChangeKind = Literal["create", "modify", "delete"]


class FileChange(BaseModel):
    """One file mutation. `before` is None for created files."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    path: str
    kind: ChangeKind
    before: str | None = None
    after: str | None = None
    ts: float = Field(default_factory=time.time)

    def diff(self) -> str:
        """Unified diff of `before` -> `after`."""
        before_lines = (self.before or "").splitlines(keepends=True)
        after_lines = (self.after or "").splitlines(keepends=True)
        rel = self.path
        a_label = f"a/{rel}" if self.before is not None else "/dev/null"
        b_label = f"b/{rel}" if self.after is not None else "/dev/null"
        return "".join(difflib.unified_diff(
            before_lines, after_lines, fromfile=a_label, tofile=b_label, n=3,
        ))


def diff_entries(entries: list["FileChange"]) -> str:
    """Collapsed unified diff over an arbitrary slice of change entries (net
    before→after per path). Lets callers diff just one turn's changes."""
    if not entries:
        return ""
    first_before: dict[str, str | None] = {}
    last_after: dict[str, str | None] = {}
    for e in entries:
        if e.path not in first_before:
            first_before[e.path] = e.before
        last_after[e.path] = e.after
    out: list[str] = []
    for path in first_before:
        before = first_before[path]
        after = last_after[path]
        if before is None and after is None:
            continue  # created then deleted — no net change
        a_label = f"a/{path}" if before is not None else "/dev/null"
        b_label = f"b/{path}" if after is not None else "/dev/null"
        joined = "".join(difflib.unified_diff(
            (before or "").splitlines(keepends=True),
            (after or "").splitlines(keepends=True),
            fromfile=a_label, tofile=b_label, n=3,
        ))
        if joined.strip():
            out.append(joined)
    return "".join(out)


class ChangeLog(BaseModel):
    """Ordered history of file changes during a session."""

    cwd: str
    entries: list[FileChange] = Field(default_factory=list)

    def record(self, path: str, *, after: str, sandbox_root: Path) -> FileChange:
        """Record a write to `path`. Computes the before-snapshot from disk."""
        rel = path
        absolute = (sandbox_root / path).resolve()
        before: str | None = None
        kind: ChangeKind = "create"
        if absolute.is_file():
            try:
                before = absolute.read_text(encoding="utf-8")
                kind = "modify"
            except (OSError, UnicodeDecodeError):
                before = None
                kind = "modify"
        entry = FileChange(path=rel, kind=kind, before=before, after=after)
        self.entries.append(entry)
        return entry

    def record_delete(self, path: str, *, sandbox_root: Path) -> FileChange | None:
        absolute = (sandbox_root / path).resolve()
        if not absolute.is_file():
            return None
        try:
            before = absolute.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            before = ""
        entry = FileChange(path=path, kind="delete", before=before, after=None)
        self.entries.append(entry)
        return entry

    def diff(self) -> str:
        """One unified diff covering every change since session start."""
        if not self.entries:
            return ""
        # Collapse multiple edits to the same path into a single before→after
        # diff (so /diff shows the net change, not a parade of incremental
        # patches).
        first_before: dict[str, str | None] = {}
        last_after: dict[str, str | None] = {}
        for e in self.entries:
            if e.path not in first_before:
                first_before[e.path] = e.before
            last_after[e.path] = e.after
        out: list[str] = []
        for path in first_before:
            if last_after[path] is None and first_before[path] is None:
                continue  # created and then deleted — no net change
            before = first_before[path]
            after = last_after[path]
            a_label = f"a/{path}" if before is not None else "/dev/null"
            b_label = f"b/{path}" if after is not None else "/dev/null"
            diff_iter = difflib.unified_diff(
                (before or "").splitlines(keepends=True),
                (after or "").splitlines(keepends=True),
                fromfile=a_label,
                tofile=b_label,
                n=3,
            )
            joined = "".join(diff_iter)
            if joined.strip():
                out.append(joined)
        return "".join(out)

    def diff_since(self, start: int) -> str:
        """Collapsed unified diff over the entries recorded since index `start`
        — i.e. just one turn's net changes, for a focused review."""
        return diff_entries(self.entries[start:])

    def undo_last(self, *, sandbox_root: Path) -> FileChange | None:
        """Revert the most recent change. Returns the entry that was undone,
        or None if there was nothing to undo."""
        if not self.entries:
            return None
        last = self.entries.pop()
        absolute = (sandbox_root / last.path).resolve()
        if last.kind == "create":
            # Newly-created file → delete it.
            try:
                if absolute.is_file():
                    absolute.unlink()
            except OSError:
                pass
        elif last.kind == "delete":
            # We had a delete — restore the file.
            absolute.parent.mkdir(parents=True, exist_ok=True)
            absolute.write_text(last.before or "", encoding="utf-8")
        else:
            absolute.parent.mkdir(parents=True, exist_ok=True)
            absolute.write_text(last.before or "", encoding="utf-8")
        return last

    def files_touched(self) -> list[str]:
        seen: list[str] = []
        for e in self.entries:
            if e.path not in seen:
                seen.append(e.path)
        return seen

    def reset(self) -> None:
        self.entries.clear()


# Module-level singleton: a per-REPL changelog. Set at session start by
# `bind_changelog(cwd)`; the apply path consults `current_changelog()`
# when recording mutations.

_LOG: ChangeLog | None = None


def bind_changelog(cwd: str | Path) -> ChangeLog:
    global _LOG
    _LOG = ChangeLog(cwd=str(Path(cwd).resolve()))
    return _LOG


def current_changelog() -> ChangeLog:
    global _LOG
    if _LOG is None:
        _LOG = ChangeLog(cwd=str(Path.cwd()))
    return _LOG


def reset_changelog() -> None:
    global _LOG
    if _LOG is not None:
        _LOG.reset()


__all__ = [
    "FileChange",
    "ChangeLog",
    "bind_changelog",
    "current_changelog",
    "reset_changelog",
]
