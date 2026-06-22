"""Learned skills — reusable how-tos the agent distills from experience.

This is essarion's self-improvement loop. After solving a non-trivial task,
the agent can distill what it figured out into a short, reusable *skill* — a
markdown brief saved under ``<project>/.essarion/skills/`` (or
``~/.essarion/skills/`` when no project is initialized). On the next task the
skill picker weighs these project-local skills alongside the 54 bundled ones,
so the agent gets measurably better at *your* codebase the more you use it.

Where a memory fact (``remember``) is one durable line, a learned skill is a
titled, multi-line procedure: "how we add a migration here", "the gotcha in
the auth refresh flow", "our preferred way to wire a new MCP tool". They are
plain markdown so humans curate them freely.

Distilled skills are quality-gated on the way in:

- **secret-screened** — a key/token-shaped value is refused, never persisted;
- **size-capped** — a skill is a brief, not a transcript dump;
- **deduplicated by name** — re-distilling a name updates it in place;
- **name-slugified** — safe, predictable filenames.

Slash commands:

- ``/distill``                  list learned skills
- ``/distill <name>: <body>``   save or update a learned skill
- ``/distill forget <name>``    delete a learned skill

The agent also distills autonomously via the ``distill_skill`` tool.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

# A learned skill is a brief, not a dump. Generous enough for a real procedure
# with a couple of code snippets, tight enough that it can't swallow a turn's
# worth of tokens every time it's injected.
MAX_SKILL_CHARS = 4000
# Slugs stay short so filenames and the picker stay readable.
MAX_SLUG_LEN = 48


class LearnedSkill(BaseModel):
    """One learned skill on disk: a slug name and its markdown body."""

    name: str
    body: str
    path: Path


def slugify(name: str) -> str:
    """Turn a free-form skill name into a safe, predictable file slug.

    Lowercases, collapses any run of non-alphanumeric characters to a single
    underscore, trims leading/trailing underscores, and caps the length.
    Raises ``ValueError`` if nothing usable survives.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    if len(slug) > MAX_SLUG_LEN:
        slug = slug[:MAX_SLUG_LEN].rstrip("_")
    if not slug:
        raise ValueError("skill name must contain at least one letter or digit")
    return slug


def learned_skills_dir(cwd: str | Path) -> Path:
    """Where learned skills live for ``cwd``.

    Per-project (``<root>/.essarion/skills/``) when the project is
    initialized, else ``~/.essarion/skills/`` as a global fallback. Mirrors
    :func:`._memory.memory_path_for` so memory and skills land together.
    """
    from ._project import find_project_root

    project = find_project_root(cwd)
    if project.has_essarion_dir:
        return project.essarion_dir / "skills"
    return Path.home() / ".essarion" / "skills"


def _normalize_body(name: str, body: str) -> str:
    """Tidy a skill body: ensure a title, cap the size, normalize whitespace."""
    body = (body or "").strip()
    if not body:
        raise ValueError("skill body must be non-empty")
    # Give the model (and the picker) an H1 to anchor on if the author didn't.
    if not body.lstrip().startswith("#"):
        title = name.replace("_", " ").strip().title()
        body = f"# {title}\n\n{body}"
    if len(body) > MAX_SKILL_CHARS:
        body = body[: MAX_SKILL_CHARS - 1].rstrip() + "…"
    return body + "\n"


def save_learned_skill(cwd: str | Path, name: str, body: str) -> tuple[Path, bool]:
    """Persist a learned skill under ``learned_skills_dir(cwd)``.

    Returns ``(path, created)`` where ``created`` is ``True`` for a brand-new
    skill and ``False`` when an existing skill of the same slug was updated.
    Refuses to store a secret-shaped body. Raises ``ValueError`` on bad input.
    """
    from ._ui import redact_secrets

    slug = slugify(name)
    if redact_secrets(body) != body:
        raise ValueError("refusing to store a secret-shaped value in a skill")
    text = _normalize_body(slug, body)
    directory = learned_skills_dir(cwd)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{slug}.md"
    created = not path.exists()
    path.write_text(text, encoding="utf-8")
    return path, created


def list_learned_skills(cwd: str | Path) -> list[str]:
    """Names (slugs, no ``.md``) of every learned skill for ``cwd``, sorted."""
    directory = learned_skills_dir(cwd)
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.md") if p.is_file())


def load_learned_skill(cwd: str | Path, name: str) -> str:
    """Read one learned skill's body. Raises ``FileNotFoundError`` if absent."""
    path = learned_skills_dir(cwd) / f"{slugify(name)}.md"
    if not path.is_file():
        raise FileNotFoundError(f"no learned skill named {name!r}")
    return path.read_text(encoding="utf-8")


def forget_learned_skill(cwd: str | Path, name: str) -> bool:
    """Delete a learned skill. Returns ``True`` if one was removed."""
    try:
        path = learned_skills_dir(cwd) / f"{slugify(name)}.md"
    except ValueError:
        return False
    if path.is_file():
        path.unlink()
        return True
    return False


def pool_bodies(cwd: str | Path) -> dict[str, str]:
    """Every learned skill for ``cwd`` as ``{name: body}``.

    This is what the skill picker ranks alongside the bundled skills and what
    the turn builder injects as custom skills. Read errors on a single file are
    swallowed — a malformed skill must never break a turn.
    """
    out: dict[str, str] = {}
    directory = learned_skills_dir(cwd)
    if not directory.is_dir():
        return out
    for md in sorted(directory.glob("*.md")):
        if not md.is_file():
            continue
        try:
            out[md.stem] = md.read_text(encoding="utf-8")
        except OSError:
            continue
    return out


__all__ = [
    "LearnedSkill",
    "MAX_SKILL_CHARS",
    "slugify",
    "learned_skills_dir",
    "save_learned_skill",
    "list_learned_skills",
    "load_learned_skill",
    "forget_learned_skill",
    "pool_bodies",
]
