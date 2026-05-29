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


DEFAULT_SECURITY_SKILLS = [
    "secure_coding",
    "auth_security",
    "code_review",
    "error_handling",
    "scope_discipline",
]

DEFAULT_PERFORMANCE_SKILLS = [
    "performance",
    "concurrency",
    "caching",
    "observability",
    "code_review",
]

DEFAULT_PR_DESCRIPTION_SKILLS = [
    "documentation",
    "code_review",
    "scope_discipline",
    "git_workflow",
]


def security_review(
    target: str,
    *,
    context: Context | None = None,
    repo: str | Path | None = None,
    diff: str | None = None,
    **kwargs,
) -> Reasoning:
    """Security-focused review. Returns a `Reasoning` whose plan reads like a
    threat-modeling pass: assets, attack surface, findings (with CWE refs
    where applicable), suggested fix."""
    ctx = _ensure_context(
        context, repo=repo, diff=diff, skills=DEFAULT_SECURITY_SKILLS
    )
    return reason(
        "Perform a security review of the following target. Your plan should "
        "(1) identify the assets being protected, (2) enumerate the attack "
        "surface visible in the context, (3) list specific findings (each "
        "with a severity, a CWE/OWASP reference where it applies, and a "
        f"concrete fix). Target: {target}",
        context=ctx,
        **kwargs,
    )


def performance_review(
    target: str,
    *,
    context: Context | None = None,
    repo: str | Path | None = None,
    diff: str | None = None,
    **kwargs,
) -> Reasoning:
    """Performance-focused review. Returns a `Reasoning` whose plan reads
    like a hot-path analysis: complexity, allocation, blocking I/O, cache
    misses, suggested optimization (with expected payoff)."""
    ctx = _ensure_context(
        context, repo=repo, diff=diff, skills=DEFAULT_PERFORMANCE_SKILLS
    )
    return reason(
        "Perform a performance review of the following target. Your plan "
        "should: (1) identify the hot path(s) in the context, (2) enumerate "
        "complexity / allocation / blocking-I/O / cache-miss issues you see, "
        "(3) suggest specific optimizations with estimated payoff and "
        f"complexity cost. Target: {target}",
        context=ctx,
        **kwargs,
    )


def write_pr_description(
    target: str,
    *,
    context: Context | None = None,
    repo: str | Path | None = None,
    diff: str | None = None,
    **kwargs,
) -> Generation:
    """Generate a PR description from a diff + context. Returns a
    `Generation` whose code field is the markdown body."""
    ctx = _ensure_context(
        context, repo=repo, diff=diff, skills=DEFAULT_PR_DESCRIPTION_SKILLS
    )
    return generate(
        "Write a pull-request description for the following change. The "
        "description must have: a one-line summary at the top, a 'Why' "
        "paragraph explaining the motivation, a 'What changes' bulleted "
        "list grounded in the diff, a 'Test plan' bulleted list, and a "
        "'Risk' line calling out anything reviewers should look at. Keep "
        "it short — readers scan PR descriptions, they do not read them. "
        f"Output the markdown body. Target: {target}",
        context=ctx,
        **kwargs,
    )


def explain_code(
    target: str,
    *,
    context: Context | None = None,
    repo: str | Path | None = None,
    **kwargs,
) -> Reasoning:
    """Explain how a piece of code works. Returns a `Reasoning` whose plan
    is a layered explanation: 1-line summary, 5-line summary, full walkthrough."""
    ctx = _ensure_context(
        context, repo=repo, diff=None, skills=["documentation", "scope_discipline"]
    )
    return reason(
        "Explain the following code to a new engineer joining the team. "
        "Plan as three layers: (1) one sentence — what it does, (2) five "
        "sentences — the algorithm at a glance, (3) the full walkthrough "
        "with file:line citations to the context. Cite specific lines; do "
        f"not paraphrase what the reader can see. Target: {target}",
        context=ctx,
        **kwargs,
    )


__all__ = [
    "review",
    "fix_bug",
    "write_tests",
    "refactor",
    "docs",
    "security_review",
    "performance_review",
    "write_pr_description",
    "explain_code",
]
