"""Redaction utilities: strip secrets and PII before sending to a provider.

Anything that goes into a `Context` is going to be sent to a third-party
model API. That includes file bodies, doc bodies, diffs, and notes. If
your repo accidentally contains an `.env` checked in for tests, or your
diff includes a customer's email, you'll send it to the model. This
module gives you a thin redactor you can run on a Context before the
provider call.

Off by default — opt in when you actually have data you care about:

    from essarion_build import Context, redact
    ctx = Context().add_repo("./src")
    redact.in_place(ctx)  # mutates: any matched secret is replaced with [REDACTED:KIND]
    # ...then pass ctx to reason() / generate()

The default patterns are deliberately conservative:
- AWS / OpenAI / Anthropic / GitHub PAT / Stripe / Slack key shapes
- Bearer tokens in HTTP headers
- Private key blocks
- Email addresses (you can disable this if you want)
- Credit-card-like number sequences

Add your own with `register_pattern(name, regex)`.
"""

from __future__ import annotations

import re
from typing import Callable

from ._context import Context


_PATTERNS: dict[str, re.Pattern[str]] = {
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "aws_secret_key": re.compile(
        r"(?i)aws_secret_access_key[\"'\s:=]+([A-Za-z0-9/+=]{40})"
    ),
    # Order matters: more-specific Anthropic / OpenRouter keys are matched
    # before the generic openai_key (which would otherwise eat them).
    "anthropic_key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    "openrouter_key": re.compile(r"\bsk-or-[A-Za-z0-9_-]{20,}\b"),
    "openai_key": re.compile(r"\bsk-(?!ant-|or-)[A-Za-z0-9_-]{20,}\b"),
    "github_pat": re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    "github_app_token": re.compile(r"\b(?:ghu|ghs|ghr)_[A-Za-z0-9]{36}\b"),
    "stripe_key": re.compile(r"\b(?:sk_live|rk_live)_[A-Za-z0-9]{24}\b"),
    "slack_token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]+\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "bearer_token": re.compile(
        r"(?i)authorization:\s*bearer\s+[A-Za-z0-9._-]+"
    ),
    "private_key_block": re.compile(
        r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC |DSA )?PRIVATE KEY-----"
    ),
    "credit_card": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "email": re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}\b"
    ),
}


def register_pattern(name: str, pattern: str | re.Pattern[str]) -> None:
    """Add a custom redaction pattern. Overrides built-ins with the same name."""
    _PATTERNS[name] = re.compile(pattern) if isinstance(pattern, str) else pattern


def unregister_pattern(name: str) -> None:
    _PATTERNS.pop(name, None)


def list_patterns() -> list[str]:
    return sorted(_PATTERNS)


def redact_text(
    text: str, *, kinds: list[str] | None = None
) -> tuple[str, list[str]]:
    """Return (redacted_text, kinds_matched).

    `kinds`, if given, restricts which patterns are applied. Default is
    every registered pattern.
    """
    out = text
    hits: list[str] = []
    applicable = kinds if kinds is not None else list(_PATTERNS)
    for kind in applicable:
        pat = _PATTERNS.get(kind)
        if pat is None:
            continue
        new = pat.sub(f"[REDACTED:{kind}]", out)
        if new != out:
            hits.append(kind)
            out = new
    return out, hits


def in_place(
    context: Context, *, kinds: list[str] | None = None
) -> dict[str, int]:
    """Mutate `context` to redact every text section. Returns a count of
    matches per kind for auditing.

    Sections redacted: repo_files, docs, diffs, notes. (Skills and source
    stubs are bundled / SDK-provided so they're not redacted.)
    """
    counts: dict[str, int] = {}

    def _apply(s: str) -> str:
        redacted, hits = redact_text(s, kinds=kinds)
        for h in hits:
            counts[h] = counts.get(h, 0) + 1
        return redacted

    for f in context.repo_files:
        f.content = _apply(f.content)
    for d in context.docs:
        d.body = _apply(d.body)
    for di in context.diffs:
        di.body = _apply(di.body)
    context.notes = [_apply(n) for n in context.notes]
    return counts


__all__ = [
    "register_pattern",
    "unregister_pattern",
    "list_patterns",
    "redact_text",
    "in_place",
]
