"""Color theme + branding for the Essarion CLI agent.

A coherent color story: cyan/teal for Essarion's brand, dim grey for
metadata, green for success, amber for "needs review", red for errors.
"""

from __future__ import annotations

from rich.theme import Theme


# Colors used across the agent UI. Hex values picked for readability on
# both light and dark terminal backgrounds.
ESSARION_THEME = Theme(
    {
        # Brand
        "brand": "bold #00d4d4",
        "brand.dim": "#5da9a9",
        # Roles
        "you": "bold #6cc7ff",
        "agent": "bold #00d4d4",
        "system": "dim white",
        # Phases of the reasoning loop
        "phase.plan": "bold magenta",
        "phase.draft": "bold cyan",
        "phase.selfcheck": "bold yellow",
        # Outcomes
        "ok": "bold green",
        "warn": "bold yellow",
        "err": "bold red",
        # Cost / budget / metadata
        "cost.under": "green",
        "cost.over": "bold red",
        "cost.warn": "yellow",
        "meta": "dim white",
        # Hints / shortcuts
        "hint": "italic dim cyan",
        "key": "bold cyan",
        # Diff
        "diff.add": "bold green",
        "diff.remove": "bold red",
        "diff.hunk": "bold blue",
        # Skills
        "skill": "italic #87d7d7",
    }
)


# ASCII banner used by the welcome screen. Picked so it fits in 80 columns
# even on narrow terminals.
BANNER = r"""[brand]
                                _                 _           _ _     _
   ___  ___ ___  __ _ _ __ (_) ___  _ __   | |__  _   _(_) | __| |
  / _ \/ __/ __|/ _` | '__| |/ _ \| '_ \  | '_ \| | | | | |/ _` |
 |  __/\__ \__ \ (_| | |  | | (_) | | | | | |_) | |_| | | | (_| |
  \___||___/___/\__,_|_|  |_|\___/|_| |_| |_.__/ \__,_|_|_|\__,_|[/brand]
"""

TAGLINE = (
    "[brand.dim]CLI coding agent · plan-first · token-efficient · BYOK[/brand.dim]\n"
    "[meta]by Essarion · amplifies any LLM with senior-engineer reasoning[/meta]"
)
