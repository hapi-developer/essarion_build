"""Pre-baked task strings for common asks.

A `recipe` is just a function that returns a (task, default_skills) pair.
Workflows already pick skill sets and frame tasks; recipes are one layer
lower, for the case where you want to call `reason()` or `generate()`
directly but want a tested, opinionated prompt rather than rolling your
own.

Pick one, call it, pass the result to `reason()` / `generate()`:

    from essarion_build import Context, reason, recipes

    task, skills = recipes.audit_for_race_conditions("the booking flow")
    ctx = Context().with_skills(skills).add_repo("./src")
    r = reason(task, context=ctx)
"""

from __future__ import annotations

from typing import Tuple


Recipe = Tuple[str, list[str]]


def audit_for_race_conditions(target: str) -> Recipe:
    return (
        f"Audit {target} for race conditions and time-of-check-to-time-of-use bugs. "
        "Your plan should: (1) identify shared mutable state in the context, "
        "(2) enumerate the access patterns that touch it from multiple goroutines/"
        "threads/coroutines, (3) flag specific TOCTOU windows, (4) suggest "
        "specific synchronization (lock, atomic, channel) per finding.",
        ["concurrency", "secure_coding", "code_review", "debugging"],
    )


def audit_for_n_plus_one(target: str) -> Recipe:
    return (
        f"Audit {target} for N+1 query patterns. Your plan should: (1) identify "
        "every loop in the context that issues a query, (2) classify whether the "
        "query depends on the loop variable, (3) propose a join/batch/in-clause "
        "fix per finding, (4) note any index that would need to exist.",
        ["performance", "database_design", "sql_idioms", "code_review"],
    )


def audit_for_n_plus_one_with_metrics(target: str) -> Recipe:
    task, skills = audit_for_n_plus_one(target)
    return (task + " For each finding, estimate the QPS impact at 10x today's traffic.", skills)


def add_typing(target: str) -> Recipe:
    return (
        f"Add type annotations to {target}. Your plan should: (1) list each "
        "public function and method that lacks types, (2) infer the right type "
        "from the body and call sites in the context, (3) introduce typed "
        "wrappers (NewType, Literal, Protocol) where a raw `str` or `int` "
        "loses information, (4) verify with `mypy --strict` mentally.",
        ["python_idioms", "scope_discipline", "refactoring"],
    )


def write_runbook(target: str) -> Recipe:
    return (
        f"Write an incident-response runbook for {target}. The runbook must "
        "include: (1) symptoms — how on-call knows this incident is happening, "
        "(2) initial triage — first three commands / dashboards to check, "
        "(3) mitigation — the kill switch / rollback / flag flip, "
        "(4) deep diagnosis — what to look at if mitigation didn't help, "
        "(5) communication template — what to say in the customer status page.",
        ["incident_response", "observability", "documentation"],
    )


def write_api_design(target: str) -> Recipe:
    return (
        f"Design an API for {target}. Your plan should: (1) enumerate the "
        "verbs (CRUD + special actions), (2) define the request/response shape "
        "for each (including error responses), (3) call out authn/authz, "
        "pagination, rate limits, idempotency, (4) match versioning style "
        "to the rest of the codebase in the context.",
        ["api_design", "secure_coding", "auth_security", "documentation"],
    )


def write_data_migration(target: str) -> Recipe:
    return (
        f"Plan a data migration for {target}. Your plan must: (1) state the "
        "before/after schema, (2) describe the backfill strategy (in-place "
        "vs. shadow column vs. dual-write), (3) order the steps so old code "
        "keeps working against new schema and new code works against old, "
        "(4) note the lock impact and how to mitigate it, (5) describe the "
        "rollback path.",
        ["migrations", "database_design", "scope_discipline", "release_engineering"],
    )


def optimize_hot_path(target: str) -> Recipe:
    return (
        f"Optimize the hot path in {target}. Plan must (1) profile mentally — "
        "which line / function dominates, (2) propose the smallest change with "
        "the largest expected payoff first, (3) reject premature optimizations "
        "that obscure the code without measurable benefit, (4) note where you "
        "would add a benchmark to lock in the win.",
        ["performance", "concurrency", "caching", "scope_discipline"],
    )


def harden_endpoint(target: str) -> Recipe:
    return (
        f"Harden the {target} endpoint against the OWASP top 10. Plan must "
        "(1) enumerate the inputs and where they reach DB / shell / network, "
        "(2) flag every place that could fall to injection, broken auth, "
        "SSRF, IDOR, or insecure deserialization, (3) propose a specific "
        "fix per finding, (4) name the regression test that would catch the "
        "issue if it reappeared.",
        ["secure_coding", "auth_security", "error_handling", "code_review"],
    )


def write_schema(target: str) -> Recipe:
    return (
        f"Design a database schema for {target}. Plan should: (1) list the "
        "entities and their relationships, (2) name the primary keys (and why), "
        "(3) note the indexes implied by the access patterns you can see in "
        "the context, (4) flag denormalization choices and the queries they "
        "speed up, (5) state nullable vs not-null per column with a one-line "
        "justification.",
        ["data_modeling", "database_design", "sql_idioms", "scope_discipline"],
    )


def list_recipes() -> list[str]:
    """The names of every recipe in this module."""
    import inspect

    return sorted(
        name
        for name, fn in globals().items()
        if not name.startswith("_")
        and inspect.isfunction(fn)
        and fn.__module__ == __name__
        and name not in {"list_recipes"}
    )


__all__ = [
    "Recipe",
    "audit_for_race_conditions",
    "audit_for_n_plus_one",
    "audit_for_n_plus_one_with_metrics",
    "add_typing",
    "write_runbook",
    "write_api_design",
    "write_data_migration",
    "optimize_hot_path",
    "harden_endpoint",
    "write_schema",
    "list_recipes",
]
