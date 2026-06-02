"""Project convention files — AGENTS.md and friends.

The agent reads project-level instruction files at the start of every turn and
injects them into the model's context, the way Claude Code reads CLAUDE.md and
Codex / Cursor / Gemini / Aider read **AGENTS.md**. Supporting the cross-tool
AGENTS.md standard means a repo already set up for any of those agents works
here with zero extra config — instant interop with the tens of thousands of
repos that ship one.

Discovery follows the AGENTS.md convention of *nearest-wins*: we walk from the
project root down to the working directory and concatenate every `AGENTS.md`
along the way, root first, so a nested file closer to `cwd` appends after (and
thus refines) the broader one. We also pick up the common single-file
conventions other tools use (CLAUDE.md, .cursorrules, …) so teams that have one
but not the other still get steered.

This is distinct from `.essarion/memory.md` (see `_memory.py`): memory is facts
the agent accumulates via `/remember`; conventions are human-authored house
rules, often shared with other agents.
"""

from __future__ import annotations

from pathlib import Path

# Single-file convention formats other agents use, in the order we present
# them. AGENTS.md is handled separately because it supports monorepo nesting.
_SINGLE_FILES = [
    "CLAUDE.md",
    ".cursorrules",
    ".windsurfrules",
    ".github/copilot-instructions.md",
    ".rules",
]

# Bound the injected text so a sprawling rules file can't blow the token budget.
_MAX_TOTAL = 12_000
_MAX_PER_FILE = 8_000


def _read_capped(path: Path, cap: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    if len(text) > cap:
        text = text[:cap].rstrip() + "\n… (truncated)"
    return text


def _agents_md_chain(root: Path, cwd: Path) -> list[Path]:
    """Every `AGENTS.md` from `root` down to `cwd`, root first (broadest) so the
    nearest file is applied last and wins on conflicts."""
    root, cwd = root.resolve(), cwd.resolve()
    try:
        rel_parts = cwd.relative_to(root).parts
    except ValueError:
        dirs = [cwd]  # cwd isn't under root — just look where we are
    else:
        dirs, cur = [root], root
        for part in rel_parts:
            cur = cur / part
            dirs.append(cur)
    return [d / "AGENTS.md" for d in dirs if (d / "AGENTS.md").is_file()]


def discover_convention_files(cwd: str | Path) -> list[Path]:
    """Ordered list of convention files in effect for `cwd` (no reading yet)."""
    from ._project import find_project_root

    cwd = Path(cwd).resolve()
    root = find_project_root(cwd).root
    files: list[Path] = list(_agents_md_chain(root, cwd))
    seen = set(files)
    for name in _SINGLE_FILES:
        p = root / name
        if p.is_file() and p not in seen:
            files.append(p)
            seen.add(p)
    return files


def load_conventions(cwd: str | Path) -> str:
    """Combined convention text for `cwd`, or "" if none exist.

    Each file is labelled by its path relative to the project root so the model
    knows where a rule came from (and which is nearest/most specific).
    """
    from ._project import find_project_root

    cwd = Path(cwd).resolve()
    root = find_project_root(cwd).root
    chunks: list[str] = []
    total = 0
    for path in discover_convention_files(cwd):
        body = _read_capped(path, _MAX_PER_FILE)
        if not body:
            continue
        try:
            label = path.relative_to(root).as_posix()
        except ValueError:
            label = path.name
        chunk = f"### {label}\n{body}"
        if total + len(chunk) > _MAX_TOTAL:
            break
        chunks.append(chunk)
        total += len(chunk)
    if not chunks:
        return ""
    return (
        "Project conventions — house rules the user expects you to follow "
        "(from AGENTS.md / convention files). Honour these unless the user's "
        "current request overrides them.\n\n" + "\n\n".join(chunks)
    )


def inject_into_context(cwd: str | Path, context) -> bool:
    """Load conventions for `cwd` and attach them to `context` as a custom
    skill. Returns True if anything was injected."""
    body = load_conventions(cwd)
    if not body:
        return False
    context.with_custom_skill("conventions", body)
    return True


__all__ = [
    "discover_convention_files",
    "load_conventions",
    "inject_into_context",
]
