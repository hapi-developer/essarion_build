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


# ASCII wordmark for the welcome screen. Built programmatically so a leading
# ">" chevron prompt (terminal-prompt motif, like the reference UI) sits to the
# left of the block letters without disturbing their internal alignment: every
# line gets a uniform 2-char prefix, and the vertical-middle line uses "> ".
_WORDMARK = r"""   ___  ___ ___  __ _ _ __(_) ___  _ __
  / _ \/ __/ __|/ _` | '__| |/ _ \| '_ \
 |  __/\__ \__ \ (_| | |  | | (_) | | | |
  \___||___/___/\__,_|_|  |_|\___/|_| |_|"""


def _with_chevron(art: str) -> str:
    lines = art.split("\n")
    mid = len(lines) // 2  # the upper-middle line carries the ">" prompt
    return "\n".join(("> " if i == mid - 1 else "  ") + ln for i, ln in enumerate(lines))


BANNER = "[brand]" + _with_chevron(_WORDMARK) + "[/brand]"

# Compact single-line wordmark for narrow terminals.
BANNER_COMPACT = "[brand]> ESSARION[/brand]"

TAGLINE = (
    "[brand.dim]CLI coding agent · autonomous · token-efficient · BYOK[/brand.dim]\n"
    "[meta]by Essarion · amplifies any LLM with senior-engineer reasoning[/meta]"
)

# "Getting started" tips shown under the wordmark (Gemini-style welcome box).
TIPS = [
    "Describe a task in plain language — the agent plans internally, then builds it on disk.",
    "It's autonomous by default: it writes, edits, runs, and fixes until done. [key]/auto off[/key] for plan-first.",
    "It can ask you questions mid-task, and [key]/budget[/key] sets a spending cap (none by default).",
    "Run [key]/help[/key] for commands, or create an [key].essarion/config.toml[/key] for defaults & hooks.",
]
