"""Quick start: load skills, ground in a repo, run reason() then generate().

Run with:
    OPENROUTER_API_KEY=... python examples/01_quick_start.py
"""

from __future__ import annotations

from essarion_build import Context, generate, reason


def main() -> None:
    ctx = (
        Context()
        .with_skills(["secure_coding", "auth_security", "error_handling", "scope_discipline"])
        .add_repo("./src")
    )
    print(f"Context size: {ctx.total_chars():,} chars ~ {ctx.estimate_tokens():,} tokens")

    print("\n--- reason() ---")
    r = reason("harden the JWT signature check against alg=none confusion", context=ctx)
    print("PLAN:\n", r.plan)
    print("\nTRADEOFFS:\n", r.tradeoffs)
    print("\nVERDICT:\n", r.verdict)
    print("\nUsage:", r.usage)

    print("\n--- generate() ---")
    g = generate("harden the JWT signature check against alg=none confusion", context=ctx)
    print("CODE:\n", g.code)
    print("\nDEFENSE:\n", g.defense)
    print("\nUsage:", g.usage)


if __name__ == "__main__":
    main()
