"""Project memory — a markdown file the agent reads every turn.

`<project>/.essarion/memory.md` (or `~/.essarion/memory.md` when no
project is initialized) holds project-specific facts the agent
should remember across sessions:

- house conventions ("use Result types, not exceptions")
- architectural shorthand ("the reasoning loop is in _runtime.py")
- decisions ("we picked PyJWT over python-jose on 2026-05-15")

The file is plain markdown so humans edit it freely. The agent reads
it at the top of each turn and injects it as a `<memory>` skill so the
model gets the team's history before planning.

Slash commands:
- `/remember <fact>`    append a line to memory
- `/remember`           print current memory
- `/forget <pattern>`   delete lines matching `pattern` (substring, case-insensitive)
- `/forget all`         wipe memory (with confirmation)
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel


_DEFAULT_HEADER = (
    "# Project memory\n"
    "\n"
    "Facts and conventions the essarion agent should remember about this "
    "project. The agent reads this file at the start of every turn and "
    "injects it into the model's context.\n"
    "\n"
    "Edit by hand or via the agent's `/remember` and `/forget` commands.\n"
    "\n"
    "## Facts\n"
)


class Memory(BaseModel):
    """One memory file, parsed into facts the agent can use."""

    path: Path
    header: str = ""
    facts: list[str] = []

    @property
    def body(self) -> str:
        """The full markdown body — what we inject into the context."""
        lines = [self.header.rstrip(), ""]
        for fact in self.facts:
            lines.append(f"- {fact}")
        return "\n".join(lines).rstrip() + "\n"

    def add_fact(self, fact: str) -> None:
        fact = fact.strip()
        if not fact:
            raise ValueError("fact must be non-empty")
        # No exact duplicates.
        if any(f.lower() == fact.lower() for f in self.facts):
            return
        self.facts.append(fact)

    def forget(self, pattern: str) -> int:
        """Remove every fact whose body matches the substring `pattern`
        (case-insensitive). Returns the number removed."""
        if not pattern.strip():
            return 0
        kept: list[str] = []
        removed = 0
        rx = re.compile(re.escape(pattern), re.IGNORECASE)
        for f in self.facts:
            if rx.search(f):
                removed += 1
            else:
                kept.append(f)
        self.facts = kept
        return removed

    def clear(self) -> None:
        self.facts = []

    def save(self) -> Path:
        """Persist back to `path`. Creates parent dirs."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.body, encoding="utf-8")
        return self.path


def memory_path_for(cwd: str | Path) -> Path:
    """Where memory lives for the given cwd.

    Per-project (`<root>/.essarion/memory.md`) when initialized, else
    `~/.essarion/memory.md` as a global fallback.
    """
    from ._project import find_project_root

    project = find_project_root(cwd)
    if project.has_essarion_dir:
        return project.essarion_dir / "memory.md"
    p = Path.home() / ".essarion" / "memory.md"
    return p


def load_memory(cwd: str | Path) -> Memory:
    """Read the memory file for `cwd`. Creates an empty Memory if missing.

    Parser is intentionally forgiving: any line starting with `- ` is a
    fact; non-fact lines are kept verbatim in the header until we hit
    the first fact line.
    """
    path = memory_path_for(cwd)
    if not path.is_file():
        return Memory(path=path, header=_DEFAULT_HEADER, facts=[])

    text = path.read_text(encoding="utf-8")
    header_lines: list[str] = []
    facts: list[str] = []
    in_facts = False
    for raw in text.splitlines():
        stripped = raw.lstrip()
        if not in_facts and stripped.startswith("- "):
            in_facts = True
        if in_facts and stripped.startswith("- "):
            facts.append(stripped[2:].rstrip())
        elif not in_facts:
            header_lines.append(raw)
        # When in_facts but the line isn't a fact (blank line between facts,
        # a heading), just drop it on the floor — the `save()` rebuild
        # canonicalizes the file.
    header = "\n".join(header_lines).strip() or _DEFAULT_HEADER
    return Memory(path=path, header=header, facts=facts)


def inject_into_context(memory: Memory, context) -> None:
    """Add the memory body to `context` as a custom skill called `memory`.

    The model sees this in every turn, alongside the bundled skills.
    """
    if not memory.facts and "Project memory" not in memory.header:
        # Nothing meaningful to inject — skip rather than send empty noise.
        return
    if not memory.facts and not memory.header.strip():
        return
    context.with_custom_skill("memory", memory.body)


__all__ = [
    "Memory",
    "memory_path_for",
    "load_memory",
    "inject_into_context",
]
