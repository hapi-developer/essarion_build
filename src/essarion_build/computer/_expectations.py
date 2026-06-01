"""Expectation-checked acting — deep reasoning at near-zero added latency.

The idea: a continuous-watcher agent is slow and hallucinates; a fire-and-hope
agent acts blind. Instead, the model declares — in the SAME action call, costing
~a dozen tokens — what it expects the action to cause:

    browser_click(selector="#login", expect="navigates to /dashboard; logout button appears")

The environment then verifies that expectation against the deterministic
post-action digest. No second model round-trip on the happy path, so the time
between actions stays low. The model is only re-engaged with a focused mismatch
note when reality and expectation diverge — which is exactly when deeper
reasoning is worth paying for. Net effect: the model is forced to think about
consequences before acting (better decisions, fewer hallucinations) without the
latency cost of an explicit reflection step.

The parser is intentionally lightweight and rule-based: it extracts checkable
claims (a URL fragment, text that should appear/disappear, "no errors") from the
free-text expectation and tests them against the digest + current URL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ._reducer import Digest


@dataclass
class Expectation:
    raw: str
    url_contains: list[str] = field(default_factory=list)
    text_appears: list[str] = field(default_factory=list)
    text_absent: list[str] = field(default_factory=list)
    expects_no_errors: bool = False
    expects_change: bool = False  # "the screen/page changes/updates" — useful when
    # there's no text to match (e.g. the desktop screen-diff tier without OCR).

    def is_checkable(self) -> bool:
        return bool(
            self.url_contains or self.text_appears or self.text_absent
            or self.expects_no_errors or self.expects_change
        )


@dataclass
class ExpectationResult:
    verdict: str  # "met" | "unmet" | "unclear"
    reasons: list[str] = field(default_factory=list)

    @property
    def met(self) -> bool:
        return self.verdict == "met"


# "appears", "shows", "displays", "navigates to /x", "no error", "should ..."
_URL_RE = re.compile(
    r"(?:navigat\w*|redirect\w*|go(?:es)?|url|route\w*|load\w*)\b[\s\w]*?(/[\w\-./?=&#]+|https?://\S+)",
    re.I,
)
# "stays on /login", "remain at /x", "on the /settings page".
_URL_RE2 = re.compile(r"\b(?:on|at|stays?\s+on|remain\w*\s+(?:on|at))\s+(/[\w\-./?=&#]+|https?://\S+)", re.I)
_QUOTED_RE = re.compile(r"[\"'“”‘’]([^\"'“”‘’]{2,60})[\"'“”‘’]")
_ABSENT_RE = re.compile(r"\b(?:no longer|disappear\w*|hidden|removed|gone|without)\b", re.I)
_NOERR_RE = re.compile(r"\bno (?:console )?errors?\b|\bwithout errors?\b|error[- ]free", re.I)
_CHANGE_RE = re.compile(
    r"\b(?:screen|page|view|ui|window|content|something|anything)\s+(?:changes?|updates?|"
    r"refreshes?|re-?renders?|redraws?)\b|\b(?:changes?|updates?)\s+appear|"
    r"\bsomething\s+happens?\b",
    re.I,
)


def parse_expectation(raw: str) -> Expectation:
    """Pull checkable claims out of a free-text expectation."""
    raw = (raw or "").strip()
    exp = Expectation(raw=raw)
    if not raw:
        return exp
    low = raw.lower()

    for rx in (_URL_RE, _URL_RE2):
        for m in rx.finditer(raw):
            frag = m.group(1).strip().rstrip(".,;")
            if frag and frag not in exp.url_contains:
                exp.url_contains.append(frag)

    absent_context = bool(_ABSENT_RE.search(raw))
    # Quoted phrases are the strongest "this exact text" signal.
    quoted = [m.group(1).strip() for m in _QUOTED_RE.finditer(raw)]
    for phrase in quoted:
        if absent_context:
            exp.text_absent.append(phrase)
        else:
            exp.text_appears.append(phrase)

    if _NOERR_RE.search(low):
        exp.expects_no_errors = True
    if _CHANGE_RE.search(raw):
        exp.expects_change = True
    return exp


def check_expectation(
    exp: Expectation, digest: Digest, *, url: str = "", page_text: str = ""
) -> ExpectationResult:
    """Test a parsed expectation against the post-action digest, current URL, and
    (when available) the page's rendered text — so "X appears/disappears" checks
    against what's actually on the page, not just the change summary."""
    if not exp.is_checkable():
        return ExpectationResult(verdict="unclear", reasons=["expectation not machine-checkable"])

    reasons: list[str] = []
    ok = True
    hay = (digest.text + "\n" + (page_text or "")).lower()
    url_l = (url or "").lower()

    for frag in exp.url_contains:
        if frag.lower() not in url_l:
            ok = False
            reasons.append(f"expected URL to contain {frag!r}, current URL is {url or '(unknown)'!r}")

    for phrase in exp.text_appears:
        if phrase.lower() not in hay and phrase.lower() not in url_l:
            ok = False
            reasons.append(f"expected to see {phrase!r}, but it was not observed")

    for phrase in exp.text_absent:
        if phrase.lower() in hay:
            ok = False
            reasons.append(f"expected {phrase!r} to be gone, but it is still present")

    if exp.expects_no_errors and digest.had_errors:
        ok = False
        reasons.append("expected no errors, but errors were observed: " + "; ".join(digest.highlights[:3]))

    if exp.expects_change and digest.n_events == 0:
        ok = False
        reasons.append("expected something to change, but nothing was observed")

    if ok:
        return ExpectationResult(verdict="met", reasons=["expectation satisfied"])
    return ExpectationResult(verdict="unmet", reasons=reasons)


def format_verdict(result: ExpectationResult) -> str:
    """A short tag prepended to a tool result so the model sees the check."""
    if result.verdict == "met":
        return "✓ expectation met"
    if result.verdict == "unclear":
        return "• expectation not auto-checkable"
    return "✗ EXPECTATION NOT MET — " + "; ".join(result.reasons)
