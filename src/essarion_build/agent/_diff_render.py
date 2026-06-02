"""Pretty rendering for unified diffs.

The minimal `render_diff` in `_ui.py` just colors each line. This module
adds:

- per-file panels (one panel per `--- a/x +++ b/x` pair) so big multi-file
  diffs are scannable
- hunk header parsing so the line numbers are accurate
- a quick stats line ("3 files changed, 12 insertions, 4 deletions")

Used by `/diff` to give a clean overview of a session's net changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text


_FILE_HEADER_RE = re.compile(r"^--- (?:a/)?(.+?)\s*$")
_FILE_HEADER_RE_B = re.compile(r"^\+\+\+ (?:b/)?(.+?)\s*$")
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class _FilePatch:
    """One per-file slice of a unified diff."""

    old_path: str = ""
    new_path: str = ""
    lines: list[str] = None  # type: ignore[assignment]
    additions: int = 0
    deletions: int = 0

    def __post_init__(self) -> None:
        if self.lines is None:
            self.lines = []


def parse_unified_diff(diff_text: str) -> list[_FilePatch]:
    """Split a unified diff into per-file `_FilePatch` records."""
    out: list[_FilePatch] = []
    current: _FilePatch | None = None
    lines = diff_text.splitlines()
    for i, line in enumerate(lines):
        # File-header detection. A *removed* source line whose text starts with
        # "-- " (SQL/Lua/Haskell comments, an email signature delimiter) renders
        # as "--- ..." in the diff, and a *added* "++ " line as "+++ ...", so a
        # bare `---`/`+++` line is ambiguous in isolation. Real unified-diff
        # headers always come as the consecutive triple
        #     --- <old>
        #     +++ <new>
        #     @@ ... @@
        # so require that exact shape before starting a new file slice — that
        # way an in-hunk "-- comment" deletion is not mistaken for a header
        # (which used to split one file into two panels and drop its counts).
        m_a = _FILE_HEADER_RE.match(line)
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        nxt2 = lines[i + 2] if i + 2 < len(lines) else ""
        if m_a and _FILE_HEADER_RE_B.match(nxt) and _HUNK_RE.match(nxt2):
            if current is not None:
                out.append(current)
            current = _FilePatch(old_path=m_a.group(1))
            current.lines.append(line)
            continue
        m_b = _FILE_HEADER_RE_B.match(line)
        if (
            m_b
            and current is not None
            and not current.new_path
            and current.lines
            and _FILE_HEADER_RE.match(current.lines[-1])
        ):
            # The `+++` half of the header pair we just opened with its `---`.
            current.new_path = m_b.group(1)
            current.lines.append(line)
            continue
        if current is None:
            # Stray content before any file header — start a synthetic patch.
            current = _FilePatch()
        current.lines.append(line)
        # Any `+`/`-` line reaching here is hunk content (the real `---`/`+++`
        # headers were consumed above), so count it — including content lines
        # that themselves begin with `++ ` / `-- `.
        if line.startswith("+"):
            current.additions += 1
        elif line.startswith("-"):
            current.deletions += 1
    if current is not None:
        out.append(current)
    return out


def _render_patch(patch: _FilePatch) -> Panel:
    """One panel per file."""
    rendered: list[Text] = []
    for line in patch.lines:
        if line.startswith("+++") or line.startswith("---"):
            rendered.append(Text(line, style="meta"))
        elif line.startswith("@@"):
            rendered.append(Text(line, style="diff.hunk"))
        elif line.startswith("+"):
            rendered.append(Text(line, style="diff.add"))
        elif line.startswith("-"):
            rendered.append(Text(line, style="diff.remove"))
        else:
            rendered.append(Text(line))

    # For a deleted file the new path is `/dev/null`; for a created file the old
    # path is. Treat `/dev/null` as empty so the panel is titled with the real
    # file that changed rather than the placeholder.
    old = "" if patch.old_path == "/dev/null" else patch.old_path
    new = "" if patch.new_path == "/dev/null" else patch.new_path
    title_path = new or old or "(diff)"
    stats = f"+{patch.additions} −{patch.deletions}"
    title = f"[brand]{title_path}[/brand]  [meta]({stats})[/meta]"
    return Panel(
        Group(*rendered),
        title=title,
        title_align="left",
        border_style="phase.draft",
        padding=(0, 1),
    )


def render_diff_pretty(console: Console, diff_text: str) -> None:
    """Render `diff_text` as one panel per file + a totals line."""
    if not diff_text.strip():
        console.print("[meta](no changes)[/meta]")
        return
    patches = parse_unified_diff(diff_text)
    if not patches:
        console.print("[meta](unparseable diff — falling back to raw render)[/meta]")
        console.print(diff_text)
        return
    for patch in patches:
        console.print(_render_patch(patch))
    total_add = sum(p.additions for p in patches)
    total_del = sum(p.deletions for p in patches)
    console.print(
        f"[meta]{len(patches)} file(s) changed · "
        f"[/meta][diff.add]+{total_add}[/diff.add] [diff.remove]−{total_del}[/diff.remove]"
    )


__all__ = ["parse_unified_diff", "render_diff_pretty"]
