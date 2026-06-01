"""Normalized observation events.

Every observer backend (browser CDP tap, desktop accessibility, screen-diff)
maps its native firehose onto this one small shape, so the reducer and the
model digest never need to know which backend produced an event. This is the
common currency that lets the reactive-observer principle generalize from the
browser to the whole computer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Higher = more worth interrupting the model for. The reducer ranks by this.
SEVERITY_ORDER: dict[str, int] = {"info": 0, "notice": 1, "warn": 2, "error": 3}


@dataclass
class ObservedEvent:
    """One thing the environment noticed.

    `kind` is a coarse category (dom, network, console, navigation, dialog,
    load, screen_diff, a11y, …); `summary` is a short human-readable line;
    `detail` carries structured extras (url, status, selector, text, count).
    """

    kind: str
    summary: str
    severity: str = "info"
    detail: dict[str, Any] = field(default_factory=dict)
    ts: float = 0.0
    source: str = "browser"  # browser | desktop | screen

    def salience(self) -> int:
        return SEVERITY_ORDER.get(self.severity, 0)


def severity_rank(severity: str) -> int:
    return SEVERITY_ORDER.get(severity, 0)
