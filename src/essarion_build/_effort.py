"""Reasoning-effort levels — spend tokens proportional to task difficulty.

This is Essarion's core bet: a cheap model reasons like a better one when
you give it the *right amount* of structured thinking — not a fixed loop.
A one-line rename shouldn't cost the same as hardening a JWT validator.

Effort levels (cheapest → deepest):

  quick     plan only. 1 reasoning call. For trivial/obvious tasks.
  standard  plan → self-check. 2 calls. The sane default.
  deep      plan → critique → revise → self-check. 4 calls. For tasks with
            real correctness/security stakes.
  max       plan → alternative plan → synthesis → critique → revise →
            self-check. 6 calls. For irreversible / high-blast-radius work.

  auto      a tiny triage call (≤1 short call) sizes the task 1-5, then
            routes: 1-2 → quick, 3 → standard, 4-5 → deep. `max` is
            opt-in only — auto never escalates to it, so auto stays cheap.

The refinement steps (critique/revise, alt/synthesize) operate on the
PLAN, which is short, so the extra calls are cheap relative to drafting
code. That's what makes "deep but still cheap" real.
"""

from __future__ import annotations

EFFORT_QUICK = "quick"
EFFORT_STANDARD = "standard"
EFFORT_DEEP = "deep"
EFFORT_MAX = "max"
EFFORT_AUTO = "auto"

# Concrete levels (auto resolves to one of these).
EFFORT_LEVELS = (EFFORT_QUICK, EFFORT_STANDARD, EFFORT_DEEP, EFFORT_MAX)
# Everything callers may pass.
VALID_EFFORTS = EFFORT_LEVELS + (EFFORT_AUTO,)

DEFAULT_EFFORT = EFFORT_STANDARD


# Refinement steps applied to the plan AFTER the initial plan call, per
# effort. Each name maps to a prompt in _prompts.py and a branch in the
# runtime. Order matters.
_PLAN_REFINEMENT: dict[str, list[str]] = {
    EFFORT_QUICK: [],
    EFFORT_STANDARD: [],
    EFFORT_DEEP: ["critique", "revise"],
    EFFORT_MAX: ["alt", "synthesize", "critique", "revise"],
}


def validate_effort(effort: str) -> str:
    """Normalize / validate an effort string. Raises ValueError on unknown."""
    e = (effort or "").strip().lower()
    if e not in VALID_EFFORTS:
        raise ValueError(
            f"Unknown effort {effort!r}. Expected one of: {', '.join(VALID_EFFORTS)}."
        )
    return e


def plan_refinement_steps(effort: str) -> list[str]:
    """The refinement step names to run after the initial plan, for `effort`."""
    return list(_PLAN_REFINEMENT.get(effort, []))


def runs_reason_selfcheck(effort: str) -> bool:
    """Whether reason() runs a final adversarial self-check.

    `quick` skips it (1 call total); everything else keeps it.
    """
    return effort != EFFORT_QUICK


def verdict_signals_risk(verdict: str) -> bool:
    """True when a verdict flags the plan/code as not yet shippable.

    Used for output-gated escalation: when the model's own self-check says
    "do not ship", `auto` spends one more refinement round rather than
    handing back a flagged plan. Adaptive on the *output*, not just the
    triaged input — and it only costs extra when the model is uncertain.
    """
    t = (verdict or "").lower()
    return (
        "do not ship" in t
        or "not ship without" in t
        or "cannot defend" in t
        or "do not merge" in t
    )


# auto escalates at most this many times on a risk signal — a hard cap so a
# perpetually-pessimistic model can't burn the budget.
MAX_AUTO_ESCALATIONS = 1


def effort_for_complexity(n: int) -> str:
    """Map a triage complexity (1-5) to a concrete effort level.

    auto deliberately tops out at `deep` — escalating to `max`
    automatically would undercut the cheap-by-default promise. Users who
    want `max` ask for it explicitly.
    """
    if n <= 2:
        return EFFORT_QUICK
    if n == 3:
        return EFFORT_STANDARD
    return EFFORT_DEEP  # 4, 5, or anything higher we ever see


def approx_reason_calls(effort: str) -> int:
    """Rough number of provider calls a reason() loop makes at `effort`.

    Used for cost projection / UI. Excludes tag-repair retries and the
    triage call for auto.
    """
    base = 1  # initial plan
    base += len(plan_refinement_steps(effort))
    if runs_reason_selfcheck(effort):
        base += 1
    return base


def approx_generate_calls(effort: str) -> int:
    """Rough number of provider calls a generate() loop makes at `effort`.

    Initial plan + refinement + draft + final code self-check.
    """
    base = 1  # initial plan
    base += len(plan_refinement_steps(effort))
    base += 1  # draft
    base += 1  # final selfcheck-with-defense
    return base


__all__ = [
    "EFFORT_QUICK",
    "EFFORT_STANDARD",
    "EFFORT_DEEP",
    "EFFORT_MAX",
    "EFFORT_AUTO",
    "EFFORT_LEVELS",
    "VALID_EFFORTS",
    "DEFAULT_EFFORT",
    "validate_effort",
    "plan_refinement_steps",
    "runs_reason_selfcheck",
    "effort_for_complexity",
    "verdict_signals_risk",
    "MAX_AUTO_ESCALATIONS",
    "approx_reason_calls",
    "approx_generate_calls",
]
