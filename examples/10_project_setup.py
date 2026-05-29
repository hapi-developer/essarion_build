"""Set up a project for the essarion CLI agent.

`essarion init` creates `<project>/.essarion/{config.toml, sessions/,
memory.md}`. This example shows the programmatic equivalent: useful for
templates, CI setup scripts, or "essarion bootstrap" wrappers.

Run with:
    python examples/10_project_setup.py
"""

from __future__ import annotations

from pathlib import Path

from essarion_build.agent import find_project_root, init_project
from essarion_build.agent._memory import load_memory


def main() -> None:
    here = Path.cwd()
    project = init_project(here)
    print(f"Initialized project at {project.root}")
    print(f"  config:   {project.essarion_dir / 'config.toml'}")
    print(f"  sessions: {project.sessions_dir}")

    # Seed project memory with a few facts the agent will see every turn.
    memory = load_memory(here)
    facts = [
        "Use type hints on all public functions",
        "Tests live in tests/ mirroring src/",
        "Prefer pathlib over os.path",
        "Run `pytest -q` before committing",
    ]
    for fact in facts:
        memory.add_fact(fact)
    memory.save()
    print(f"  memory:   {len(memory.facts)} fact(s) seeded ({memory.path})")

    # Custom slash command.
    cmd_dir = project.essarion_dir / "commands"
    cmd_dir.mkdir(exist_ok=True)
    (cmd_dir / "tldr.md").write_text(
        "Summarize {args} in one paragraph. Cite specific files and "
        "line numbers from the context.\n"
    )
    print(f"  commands: /tldr → {cmd_dir / 'tldr.md'}")

    # Verify the project root is detected from a nested dir.
    nested = here / "tests"
    if nested.is_dir():
        detected = find_project_root(nested)
        print(f"\nFrom {nested}, detected project root: {detected.root}")
        print(f"  (matched on {detected.detected_by!r})")


if __name__ == "__main__":
    main()
