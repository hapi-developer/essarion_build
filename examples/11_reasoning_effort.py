"""Adaptive reasoning effort — spend tokens proportional to task difficulty.

Shows the four explicit effort levels and `auto` (which sizes the task
for you). Run with a cheap model to feel the difference:

    OPENROUTER_API_KEY=... python examples/11_reasoning_effort.py
"""

from __future__ import annotations

from essarion_build import Context, approx_reason_calls, reason

ctx = Context().with_skills(["secure_coding", "auth_security", "concurrency"])

TRIVIAL = "rename the variable `cfg` to `config` in a small module"
HARD = "make a token-bucket rate limiter safe under concurrent access"


def show(task: str, effort: str) -> None:
    r = reason(task, context=ctx, effort=effort)
    print(f"\n=== effort={effort!r}  (~{approx_reason_calls(r.effort)} calls) ===")
    print(f"resolved effort: {r.effort}")
    print(f"tokens: {r.usage.total_tokens:,}")
    print("plan (first 3 lines):")
    for line in r.plan.splitlines()[:3]:
        print("   ", line)
    print("verdict:", r.verdict[:160])


def main() -> None:
    # Pin the depth yourself...
    show(TRIVIAL, "quick")       # 1 call — don't over-think a rename
    show(HARD, "deep")           # 4 calls — critique + revise the plan
    show(HARD, "max")            # 6 calls — explore an alternative, synthesize

    # ...or let triage decide. Trivial sizes down, hard sizes up.
    print("\n--- auto: triage sizes each task ---")
    show(TRIVIAL, "auto")        # likely resolves to "quick"
    show(HARD, "auto")           # likely resolves to "deep"


if __name__ == "__main__":
    main()
