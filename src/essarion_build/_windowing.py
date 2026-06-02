"""Semantic windowing for large text — keep the meaningful parts, drop the middle.

Naive truncation (``text[:N]``) silently discards the *tail* of a file, which is
exactly where important logic often lives: a class's later methods, a module's
``if __name__ == "__main__"`` guard, the function that actually does the work.
A model handed only a blind prefix reasons about half a file and misses the rest.

These helpers do better:

* :func:`head_tail_window` keeps both ends with a marker in the middle, so the
  start *and* the end of a large file survive truncation.
* :func:`window_around_lines` / :func:`window_around_pattern` center the kept
  window on the lines that matter (search hits) plus the enclosing
  function/class header, so the model sees relevant code *with* its definitional
  context instead of an arbitrary slice.
* :func:`smart_truncate` is the one-call dispatcher the rest of the codebase
  uses.

Every marker emitted by this module contains the word "truncated" so callers and
tests can reliably detect that windowing happened.
"""

from __future__ import annotations

import re

# Lines that open a logical block in the languages we deal with most. Used to
# extend a window *upward* to the nearest definition header, so a matched line
# is shown together with the signature it belongs to. Deliberately permissive —
# a false positive just keeps one extra (relevant-looking) line.
_HEADER_RE = re.compile(
    r"^\s*(?:"
    r"(?:async\s+)?def\b|class\b|"  # Python
    r"(?:export\s+)?(?:default\s+)?(?:async\s+)?function\b|"  # JS/TS
    r"(?:public|private|protected|static|func|fn|impl|interface|type|struct|enum)\b|"
    r"[A-Za-z_$][\w$]*\s*[:=]\s*(?:async\s*)?\([^)]*\)\s*=>"  # JS arrow assignment
    r")"
)


def _truncation_marker(dropped_chars: int, dropped_lines: int | None = None) -> str:
    """A one-line, self-describing elision marker (always says "truncated")."""
    line_part = f", {dropped_lines:,} lines" if dropped_lines else ""
    return f"\n… (truncated {dropped_chars:,} chars{line_part}) …\n"


def head_tail_window(
    text: str,
    *,
    max_chars: int,
    head_ratio: float = 0.6,
) -> str:
    """Truncate ``text`` to ~``max_chars`` while preserving BOTH ends.

    ``head_ratio`` of the budget goes to the start, the remainder to the end,
    cut on line boundaries where possible. The dropped middle is replaced with a
    marker noting how much was elided. Small inputs are returned unchanged.
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head_budget = max(0, int(max_chars * head_ratio))
    tail_budget = max(0, max_chars - head_budget)

    head = text[:head_budget]
    tail = text[len(text) - tail_budget:] if tail_budget else ""
    # Prefer to cut on line boundaries so we don't slice a token in half.
    nl = head.rfind("\n")
    if nl > head_budget // 2:
        head = head[: nl + 1]
    nl = tail.find("\n")
    if 0 <= nl < tail_budget // 2:
        tail = tail[nl + 1:]

    dropped = len(text) - len(head) - len(tail)
    dropped_lines = text.count("\n") - head.count("\n") - tail.count("\n")
    return head + _truncation_marker(dropped, max(0, dropped_lines)) + tail


def _nearest_header(lines: list[str], idx: int, *, look_back: int = 25) -> int:
    """Index of the nearest block header at or above ``idx`` (or ``idx`` itself).

    Lets a window include the ``def``/``class`` line a matched line lives under,
    so a hit deep inside a function is shown with the signature that frames it.
    """
    for i in range(idx, max(-1, idx - look_back) - 1, -1):
        if _HEADER_RE.match(lines[i]):
            return i
    return idx


def window_around_lines(
    text: str,
    line_numbers: list[int],
    *,
    max_chars: int,
    context: int = 6,
) -> str:
    """Keep windows of ``text`` centered on the given 1-based ``line_numbers``.

    Each window spans ``context`` lines either side of a hit, extended up to the
    nearest enclosing function/class header. Overlapping windows merge; gaps
    between them become elision markers. If the result would still exceed
    ``max_chars`` the windows are trimmed fairly. With no usable line numbers
    this falls back to :func:`head_tail_window`.
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    lines = text.split("\n")
    n = len(lines)
    hits = sorted({ln - 1 for ln in line_numbers if 1 <= ln <= n})
    if not hits:
        return head_tail_window(text, max_chars=max_chars)

    # Build (start, end) inclusive ranges, extended to the enclosing header.
    ranges: list[list[int]] = []
    for h in hits:
        start = _nearest_header(lines, max(0, h - context))
        end = min(n - 1, h + context)
        if ranges and start <= ranges[-1][1] + 1:
            ranges[-1][1] = max(ranges[-1][1], end)
        else:
            ranges.append([start, end])

    # If even the windows blow the budget, shrink them evenly from a fair share.
    budget_lines = max(len(ranges) * (context + 1), max_chars // 40)
    total_span = sum(e - s + 1 for s, e in ranges)
    if total_span > budget_lines:
        per = max(context, budget_lines // max(1, len(ranges)))
        for r in ranges:
            mid = (r[0] + r[1]) // 2
            r[0] = max(0, mid - per // 2)
            r[1] = min(n - 1, mid + per // 2)

    out: list[str] = []
    if ranges[0][0] > 0:
        out.append(f"… (truncated {ranges[0][0]:,} lines above) …")
    for i, (s, e) in enumerate(ranges):
        if i > 0:
            gap = s - ranges[i - 1][1] - 1
            if gap > 0:
                out.append(f"… (truncated {gap:,} lines) …")
        out.append(f"@@ lines {s + 1}-{e + 1} @@")
        out.extend(lines[s : e + 1])
    if ranges[-1][1] < n - 1:
        out.append(f"… (truncated {n - 1 - ranges[-1][1]:,} lines below) …")

    rendered = "\n".join(out)
    # Last-resort cap so a pathological match set can't exceed the budget.
    if len(rendered) > max_chars:
        rendered = head_tail_window(rendered, max_chars=max_chars)
    return rendered


def window_around_pattern(
    text: str,
    pattern: str,
    *,
    max_chars: int,
    context: int = 6,
    flags: int = re.IGNORECASE,
) -> str:
    """Window ``text`` around lines matching the regex ``pattern``.

    Falls back to :func:`head_tail_window` when the pattern is empty, invalid,
    or matches nothing.
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if not pattern:
        return head_tail_window(text, max_chars=max_chars)
    try:
        rx = re.compile(pattern, flags)
    except re.error:
        return head_tail_window(text, max_chars=max_chars)
    line_numbers = [i for i, line in enumerate(text.split("\n"), start=1) if rx.search(line)]
    if not line_numbers:
        return head_tail_window(text, max_chars=max_chars)
    return window_around_lines(text, line_numbers, max_chars=max_chars, context=context)


def smart_truncate(
    text: str,
    *,
    max_chars: int,
    pattern: str | None = None,
    context: int = 6,
) -> str:
    """One-call entry point.

    With a ``pattern``, keep windows around the matching lines (and their
    enclosing definitions); without one, keep the head and the tail. Either way
    the middle is elided with a self-describing "truncated" marker rather than
    silently dropped.
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if pattern:
        return window_around_pattern(text, pattern, max_chars=max_chars, context=context)
    return head_tail_window(text, max_chars=max_chars)


__all__ = [
    "head_tail_window",
    "window_around_lines",
    "window_around_pattern",
    "smart_truncate",
]
