"""Enable ``python -m essarion_build`` as a PATH-independent entry point.

Delegates to the same callable as the ``essarion`` / ``essarion-build``
console scripts (see ``[project.scripts]`` in ``pyproject.toml``), so running
the module is equivalent to running the installed command — useful when the
console script's directory isn't on ``PATH``.
"""

from __future__ import annotations

import sys

from .agent.main import main_or_subcommand

if __name__ == "__main__":
    sys.exit(main_or_subcommand())
