"""High-level workflows: convenience wrappers for the most common coding tasks.

Each workflow:
1. Picks a sensible default skill set for the kind of task.
2. Wraps the task in a phrasing that nudges the model toward the right shape.
3. Calls `reason()` or `generate()` with the user's Context (or one created
   from a path) plus the workflow-specific skills.

They're thin on purpose. If your task fits one, great — if not, drop down
to `reason()` / `generate()` and build your own Context.
"""

from __future__ import annotations

from pathlib import Path

from ._context import Context
from ._generate import Generation, generate
from ._reasoning import Reasoning, reason

DEFAULT_REVIEW_SKILLS = [
    "code_review",
    "secure_coding",
    "error_handling",
    "scope_discipline",
    "performance",
]

DEFAULT_BUGFIX_SKILLS = [
    "debugging",
    "testing",
    "secure_coding",
    "error_handling",
    "scope_discipline",
]

DEFAULT_TEST_SKILLS = [
    "testing",
    "code_review",
    "scope_discipline",
    "python_idioms",
]

DEFAULT_REFACTOR_SKILLS = [
    "refactoring",
    "scope_discipline",
    "code_review",
    "performance",
    "testing",
]

DEFAULT_DOCS_SKILLS = [
    "documentation",
    "scope_discipline",
    "api_design",
]


def _ensure_context(
    context: Context | None,
    *,
    repo: str | Path | None,
    diff: str | None,
    skills: list[str],
) -> Context:
    ctx = context if context is not None else Context()
    if repo is not None:
        ctx.add_repo(repo)
    if diff is not None:
        ctx.add_diff(diff, title="review-target")
    # Only add skills not already present.
    existing = {s.name for s in ctx.builtin_skills}
    to_add = [s for s in skills if s not in existing]
    if to_add:
        ctx.with_skills(to_add)
    return ctx


def review(
    target: str,
    *,
    context: Context | None = None,
    repo: str | Path | None = None,
    diff: str | None = None,
    **kwargs,
) -> Reasoning:
    """Code-review workflow. Returns a `Reasoning` whose plan reads like a
    review: findings, severity, suggested fix.

    Pass `diff=...` to focus on a change set, or `repo=...` to review the
    whole thing.
    """
    ctx = _ensure_context(context, repo=repo, diff=diff, skills=DEFAULT_REVIEW_SKILLS)
    return reason(
        f"Review the following target for correctness, security, and "
        f"maintainability. Treat your plan as a list of review findings, "
        f"each with a severity and a concrete suggested fix. Target: {target}",
        context=ctx,
        **kwargs,
    )


def fix_bug(
    bug_report: str,
    *,
    context: Context | None = None,
    repo: str | Path | None = None,
    diff: str | None = None,
    **kwargs,
) -> Generation:
    """Bug-fix workflow. Returns a `Generation` whose code field is the patch."""
    ctx = _ensure_context(context, repo=repo, diff=diff, skills=DEFAULT_BUGFIX_SKILLS)
    return generate(
        "Fix the following bug. Your plan should: "
        "(1) restate the bug in one line, "
        "(2) trace it to a root cause in the provided context, "
        "(3) describe the minimal patch, "
        "(4) describe a regression test that would catch it. "
        f"Then output the patch as code. Bug report: {bug_report}",
        context=ctx,
        **kwargs,
    )


def write_tests(
    target: str,
    *,
    context: Context | None = None,
    repo: str | Path | None = None,
    **kwargs,
) -> Generation:
    """Generate tests for a target. Returns a `Generation` whose code field
    is the test file."""
    ctx = _ensure_context(context, repo=repo, diff=None, skills=DEFAULT_TEST_SKILLS)
    return generate(
        "Write tests for the following target. Cover the golden path, two "
        "edge cases, and one regression case based on the existing code in "
        f"the context. Target: {target}",
        context=ctx,
        **kwargs,
    )


def refactor(
    target: str,
    *,
    context: Context | None = None,
    repo: str | Path | None = None,
    diff: str | None = None,
    **kwargs,
) -> Generation:
    """Refactor workflow. Returns a `Generation` whose code field is the
    refactored version."""
    ctx = _ensure_context(context, repo=repo, diff=diff, skills=DEFAULT_REFACTOR_SKILLS)
    return generate(
        "Refactor the following target. Preserve external behavior; improve "
        "internal structure. Plan must explicitly list each behavior that "
        "must be preserved and how the refactor preserves it. Avoid "
        f"speculative generality. Target: {target}",
        context=ctx,
        **kwargs,
    )


def docs(
    target: str,
    *,
    context: Context | None = None,
    repo: str | Path | None = None,
    **kwargs,
) -> Generation:
    """Documentation workflow. Returns a `Generation` whose code field is
    the doc body (markdown unless the target dictates otherwise)."""
    ctx = _ensure_context(context, repo=repo, diff=None, skills=DEFAULT_DOCS_SKILLS)
    return generate(
        "Write documentation for the following target. Match the existing "
        "doc style in the context if any. Cover: what it does, when to use "
        "it, when NOT to use it, one runnable example, and the failure "
        f"modes. Target: {target}",
        context=ctx,
        **kwargs,
    )


__all__ = ["review", "fix_bug", "write_tests", "refactor", "docs"]
