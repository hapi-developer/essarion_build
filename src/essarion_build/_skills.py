"""Loader for the bundled software-development skills.

Skills live as markdown files under `essarion_build/skills/`. They are
short, model-readable summaries of widely-agreed-on engineering practice
(secure coding, testing, error handling, API design, …). The point is to
amplify the reasoning of *any* model — including cheap ones — by giving it
the same skills a thoughtful senior engineer would bring to the task.
"""

from __future__ import annotations

from importlib.resources import files
from typing import Iterable

_SKILLS_PACKAGE = "essarion_build.skills"


def list_skills() -> list[str]:
    """Return the names of all bundled skills (sorted, no `.md` suffix)."""
    skill_dir = files(_SKILLS_PACKAGE)
    names: list[str] = []
    for entry in skill_dir.iterdir():
        name = entry.name
        if name.endswith(".md"):
            names.append(name[: -len(".md")])
    return sorted(names)


def load_skill(name: str) -> str:
    """Read a single bundled skill's markdown body. Raises FileNotFoundError if unknown."""
    skill_file = files(_SKILLS_PACKAGE) / f"{name}.md"
    if not skill_file.is_file():
        raise FileNotFoundError(
            f"No bundled skill named {name!r}. "
            f"Available: {', '.join(list_skills())}"
        )
    return skill_file.read_text(encoding="utf-8")


def load_skills(names: Iterable[str]) -> list[tuple[str, str]]:
    """Load several skills at once. Returns (name, body) tuples in input order."""
    return [(n, load_skill(n)) for n in names]
