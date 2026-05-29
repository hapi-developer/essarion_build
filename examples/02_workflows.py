"""High-level workflows: review, fix_bug, write_tests, refactor, docs.

Run with:
    OPENROUTER_API_KEY=... python examples/02_workflows.py
"""

from __future__ import annotations

import subprocess

from essarion_build import Context, workflows


def review_current_diff() -> None:
    diff = subprocess.check_output(["git", "diff", "HEAD"]).decode()
    if not diff.strip():
        print("(no uncommitted changes — review skipped)")
        return
    ctx = Context().add_repo("./src", max_files=20)
    r = workflows.review("the current diff", context=ctx, diff=diff)
    print("REVIEW PLAN:\n", r.plan)
    print("\nVERDICT:\n", r.verdict)


def fix_a_bug() -> None:
    ctx = Context().add_repo("./src", include=["**/*.py"], max_files=10)
    g = workflows.fix_bug(
        "the OpenRouter provider should retry on 502 status, not just 429",
        context=ctx,
    )
    print("FIX:\n", g.code)


def write_some_tests() -> None:
    ctx = Context().add_file("./src/essarion_build/_cache.py")
    g = workflows.write_tests("the ResponseCache class", context=ctx)
    print("TESTS:\n", g.code)


if __name__ == "__main__":
    print("--- review ---")
    review_current_diff()
    print("\n--- fix_bug ---")
    fix_a_bug()
    print("\n--- write_tests ---")
    write_some_tests()
