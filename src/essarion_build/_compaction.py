"""Context compaction: shrink an over-budget Context to fit a token cap.

When `Context.estimate_tokens()` says you're way over budget, you have
three options:

1. Trim files (the loaded repo is too big)
2. Trim docs (some external doc page is huge)
3. Summarize older repo files

This module implements deterministic versions of (1) and (2) — straight
truncation by character budget — plus a simple bottom-up keep-order pass
so the most relevant content (skills, notes, diffs) stays intact.

There's no model call here. If you want LLM-driven summarization, build
on `reason()` separately.
"""

from __future__ import annotations

from ._context import Context


# Order matters: things later in the list are dropped first.
_DROP_ORDER = ("repo_files", "docs")


def compact(context: Context, *, max_tokens: int) -> Context:
    """Return a NEW Context whose estimated token count is <= `max_tokens`.

    Strategy:
    1. If under budget, return a copy unchanged.
    2. Otherwise drop entries from the back of `repo_files`, then `docs`,
       in that order. Skills, diffs, and notes are NEVER dropped — they
       are the high-signal content.

    Always returns at least the high-signal sections (skills/notes/diffs).
    If those alone exceed `max_tokens`, you'll get back the same Context
    (compaction can't go further without losing intent).
    """
    if context.estimate_tokens() <= max_tokens:
        return context.model_copy(deep=True)

    out = context.model_copy(deep=True)
    for kind in _DROP_ORDER:
        items = getattr(out, kind)
        # Drop from the back (latest add_*) until we fit or run out.
        while items and out.estimate_tokens() > max_tokens:
            items.pop()
        if out.estimate_tokens() <= max_tokens:
            return out
    return out


def truncate_files(
    context: Context, *, max_chars_per_file: int
) -> Context:
    """Return a NEW Context where every repo file's content is truncated to
    `max_chars_per_file` characters (with an explicit marker)."""
    out = context.model_copy(deep=True)
    for f in out.repo_files:
        if len(f.content) > max_chars_per_file:
            head = f.content[:max_chars_per_file]
            f.content = (
                head
                + f"\n\n# … (truncated; original was {len(f.content):,} chars)"
            )
    return out


def keep_only_files(context: Context, *, patterns: list[str]) -> Context:
    """Return a NEW Context keeping only repo files whose paths match any
    of `patterns` (fnmatch globs). Useful for "focus on src/auth/**"."""
    import fnmatch

    out = context.model_copy(deep=True)
    out.repo_files = [
        f for f in out.repo_files
        if any(fnmatch.fnmatch(f.path, pat) for pat in patterns)
    ]
    return out


__all__ = ["compact", "truncate_files", "keep_only_files"]
