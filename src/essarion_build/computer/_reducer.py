"""The reducer — the heart of the reactive observer.

A raw observation stream is a noisy firehose: hundreds of DOM mutations, dozens
of network calls, repeated console lines. Handing that to the model verbatim
would be slow, expensive, and hallucination-prone. The reducer debounces,
deduplicates, merges, ranks by salience, and budget-caps the stream into a
small structured-text *digest* — the only thing the model ever sees.

It is deliberately deterministic and model-free so it's fast (microseconds) and
testable with synthetic event streams. The action latency of the whole agent
depends on this staying cheap.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

from ._events import ObservedEvent, severity_rank


@dataclass
class Digest:
    """The reduced, budget-sized view of what changed since the last action."""

    text: str
    counts: dict[str, int] = field(default_factory=dict)
    highlights: list[str] = field(default_factory=list)
    had_errors: bool = False
    n_events: int = 0
    n_groups: int = 0

    def is_meaningful(self) -> bool:
        """Whether anything worth acting on happened. The act→observe→act loop
        uses this to decide if the model even needs to be re-engaged."""
        return self.had_errors or bool(self.highlights) or self.n_events > 0


_EMPTY_TEXT = "no significant change observed"


def reduce_events(
    events: list[ObservedEvent],
    *,
    budget_lines: int = 12,
    max_chars: int = 1400,
    min_severity: str = "info",
) -> Digest:
    """Collapse a raw event stream into a compact digest.

    * merge identical (kind, summary) events into one line with a ``×N`` count,
    * keep the highest severity and most recent timestamp seen in each group,
    * rank groups by severity, then frequency, then recency,
    * drop groups below ``min_severity`` — unless an error exists, in which case
      everything stays visible so context isn't lost,
    * cap to ``budget_lines`` lines and ``max_chars`` characters.
    """
    min_rank = severity_rank(min_severity)

    groups: "OrderedDict[tuple[str, str], dict]" = OrderedDict()
    counts_by_kind: dict[str, int] = {}
    for ev in events:
        counts_by_kind[ev.kind] = counts_by_kind.get(ev.kind, 0) + 1
        key = (ev.kind, ev.summary)
        g = groups.get(key)
        if g is None:
            groups[key] = {"ev": ev, "count": 1, "rank": ev.salience(), "ts": ev.ts}
        else:
            g["count"] += 1
            if ev.salience() > g["rank"]:
                g["ev"], g["rank"] = ev, ev.salience()
            g["ts"] = max(g["ts"], ev.ts)

    ranked = sorted(
        groups.values(),
        key=lambda g: (g["rank"], g["count"], g["ts"]),
        reverse=True,
    )
    had_errors = any(g["rank"] >= severity_rank("error") for g in ranked)

    # Filter to salient groups, but never hide errors. If filtering removes
    # everything, keep the single most salient group so the digest isn't blind.
    if had_errors:
        visible = ranked
    else:
        visible = [g for g in ranked if g["rank"] >= min_rank] or ranked[:1]

    lines: list[str] = []
    highlights: list[str] = []
    used = 0
    for i, g in enumerate(visible):
        ev = g["ev"]
        suffix = f" (×{g['count']})" if g["count"] > 1 else ""
        line = f"[{ev.severity}] {ev.kind}: {ev.summary}{suffix}"
        if len(lines) >= budget_lines or used + len(line) > max_chars:
            lines.append(f"… (+{len(visible) - i} more change-groups)")
            break
        lines.append(line)
        used += len(line) + 1
        if g["rank"] >= severity_rank("warn"):
            highlights.append(ev.summary)

    text = "\n".join(lines) if lines else _EMPTY_TEXT
    return Digest(
        text=text,
        counts=counts_by_kind,
        highlights=highlights,
        had_errors=had_errors,
        n_events=len(events),
        n_groups=len(groups),
    )
