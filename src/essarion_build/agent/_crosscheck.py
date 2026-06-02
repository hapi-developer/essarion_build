"""Cross-model second opinion — an INDEPENDENT model red-teams a change.

The thesis: different model families have different blind spots, so where two
models *disagree* about a change is exactly where bugs hide. A model's own
self-check tends to rubber-stamp its work; a different model, handed only the
goal and the diff (never the whole repo, so it stays cheap), is a real second
pair of eyes.

This is the cheap-ensemble reading of Essarion's whole thesis: instead of one
expensive model, make several *cheap* models — one to build, a different one to
cross-examine — reason like a careful senior reviewer, for pennies. No mainstream
coding agent runs an independent cross-model adversarial gate by default.

Token discipline is the point: the reviewer sees the goal + the (windowed) diff
and nothing else, and answers in a tight tagged format. A full review is usually
a few hundred output tokens.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from .._providers import Usage
from .._windowing import head_tail_window

# How much of a (possibly large) diff we send. Windowed head+tail so a giant
# change still costs a bounded amount to review.
_MAX_CHANGE_CHARS = 12_000
# Output cap for the review — a second opinion is short by design.
_DEFAULT_MAX_TOKENS = 700

_PLACEHOLDER_CONCERNS = {"none", "n/a", "na", "no concerns", "(none)", "-", "—", "nothing"}


class SecondOpinion(BaseModel):
    """One independent cross-model review of a change."""

    agree: bool = True            # does the reviewer think it's safe to ship?
    concerns: list[str] = Field(default_factory=list)
    summary: str = ""
    model: str = ""
    usage: Usage = Field(default_factory=Usage)
    cost_usd: float = 0.0
    ok: bool = True               # False if the review CALL itself failed
    error: str = ""

    @property
    def disagrees(self) -> bool:
        """A real, actionable disagreement: the call succeeded and the reviewer
        either said no or surfaced concerns despite saying yes."""
        return self.ok and (not self.agree or bool(self.concerns))


_SYSTEM = (
    "You are a meticulous senior engineer giving an INDEPENDENT second opinion on "
    "a code change someone else wrote. You did not write it and have no stake in "
    "it — your job is to find what's WRONG (the bug, the security hole, the broken "
    "edge case, the unhandled failure), not to praise it. Be specific and cite the "
    "file and symbol/line. If, after a genuinely adversarial read, you find nothing "
    "that would block shipping, say so plainly rather than inventing nitpicks."
)

_PROMPT = (
    "GOAL the change was meant to accomplish:\n{goal}\n\n"
    "THE CHANGE (unified diff):\n{change}\n\n"
    "Review it adversarially through three lenses: (1) correctness & edge cases; "
    "(2) security / trust boundaries — shell, subprocess, untrusted input, path "
    "handling, injection; (3) concurrency & resource lifecycle — shared mutable "
    "state, races, leaks, missing cleanup. Respond with EXACTLY this XML and "
    "nothing else:\n\n"
    "<agree>yes|no</agree>\n"
    "<concerns>\n"
    "- file:symbol — the concrete problem and the failure it invites (one per "
    "line; leave empty if you genuinely found none)\n"
    "</concerns>\n"
    "<summary>One sentence: ship, or do-not-ship-until-X.</summary>"
)


def _extract(tag: str, text: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _parse(text: str, model: str, usage: Usage) -> SecondOpinion:
    agree_raw = _extract("agree", text).lower()
    # Default to "disagree" only on an explicit no; a missing/garbled tag with no
    # concerns reads as agreement (don't block on a malformed review).
    agree = not any(w in agree_raw for w in ("no", "do not", "don't", "block"))
    concerns_block = _extract("concerns", text)
    concerns: list[str] = []
    for line in concerns_block.splitlines():
        c = line.strip().lstrip("-*•").strip()
        if c and c.lower() not in _PLACEHOLDER_CONCERNS:
            concerns.append(c)
    summary = _extract("summary", text)
    return SecondOpinion(
        agree=agree, concerns=concerns, summary=summary, model=model, usage=usage
    )


def request_second_opinion(
    provider,
    *,
    goal: str,
    change: str,
    model: str = "",
    max_tokens: int = _DEFAULT_MAX_TOKENS,
) -> SecondOpinion:
    """Ask `provider` (ideally a different model) for an independent review of
    `change`. Token-light: only the goal + the windowed diff are sent — never the
    repo context. Never raises; a failed call comes back as `ok=False`."""
    windowed = head_tail_window(change, max_chars=_MAX_CHANGE_CHARS)
    user = _PROMPT.format(goal=(goal or "").strip()[:2000], change=windowed)
    try:
        resp = provider.complete(
            system=_SYSTEM, messages=[{"role": "user", "content": user}], max_tokens=max_tokens
        )
    except Exception as e:  # noqa: BLE001 - a failed review must never crash a turn
        return SecondOpinion(ok=False, error=f"{type(e).__name__}: {e}", model=model)
    usage = getattr(resp, "usage", None) or Usage()
    return _parse(resp.text or "", model or getattr(provider, "model", ""), usage)


__all__ = ["SecondOpinion", "request_second_opinion"]
