"""Subagents — focused workers the main agent can dispatch in parallel.

The main agent does plan → draft → selfcheck on the user's task. Some
tasks benefit from breaking the work into independent pieces a fleet of
small agents can attack at once:

- a `researcher` reads relevant files and reports facts
- a `test-writer` drafts the tests for the change
- an `implementer` drafts the code
- a `verifier` runs the test suite and reports failures
- a `reviewer` reads the draft adversarially

`run_subagents_parallel(specs, parent_context=ctx)` runs them
concurrently, aggregates the usage, and returns one `SubAgentResult` per
spec. The main agent then synthesizes the findings into a single plan
or draft.

Why this is its own module (not just `Conversation`/`Batch`): subagents
share **inherited context** with the parent (skills, repo files, notes)
but each gets a focused task and an optional file scope — they aren't
parallel independent calls, they're focused workers on the same change.
"""

from __future__ import annotations

import concurrent.futures
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .. import (
    Context,
    Generation,
    LiteRuntime,
    Reasoning,
    Usage,
    build_provider,
    generate,
    reason,
)
from .._context import RepoFile


SubAgentRole = Literal[
    "researcher",
    "implementer",
    "test_writer",
    "verifier",
    "reviewer",
    "refactorer",
    "custom",
]


# Default skill set per role. Keeps each subagent on-task without the
# main agent's wide skill load.
_ROLE_SKILLS: dict[SubAgentRole, list[str]] = {
    "researcher": ["code_search", "documentation", "scope_discipline"],
    "implementer": ["python_idioms", "secure_coding", "error_handling",
                    "scope_discipline"],
    "test_writer": ["testing", "scope_discipline", "code_review"],
    "verifier": ["testing", "debugging", "observability_practice"],
    "reviewer": ["code_review", "code_review_practice", "secure_coding",
                 "scope_discipline"],
    "refactorer": ["refactoring", "code_smells", "scope_discipline",
                   "code_review"],
    "custom": [],
}


# What kind of SDK call a role makes by default.
_ROLE_MODE: dict[SubAgentRole, str] = {
    "researcher": "reason",
    "implementer": "generate",
    "test_writer": "generate",
    "verifier": "reason",
    "reviewer": "reason",
    "refactorer": "generate",
    "custom": "reason",
}


# Per-role task framing — wraps the user's task so each subagent has a
# clear scope without the main agent having to re-prompt each time.
_ROLE_FRAMING: dict[SubAgentRole, str] = {
    "researcher": (
        "You are a research subagent. Your only job is to gather facts "
        "from the provided context and produce a concise findings list. "
        "Do NOT propose code. Report bullet points, each citing the file "
        "and line where you found the evidence.\n\nTask: {task}"
    ),
    "implementer": (
        "You are an implementer subagent. Your job is to write the code "
        "that implements the user's task. The plan should be specific to "
        "the implementation choices (data structures, names, error paths). "
        "Skip exploratory analysis — the researcher does that.\n\nTask: {task}"
    ),
    "test_writer": (
        "You are a test-writer subagent. Your job is to write tests for "
        "the user's task. Cover the golden path, two edge cases, and one "
        "regression case. Use the test conventions present in the context.\n\n"
        "Task: {task}"
    ),
    "verifier": (
        "You are a verifier subagent. The user has provided either test "
        "output or a draft change. Your job is to report whether it is "
        "shippable. Flag every failure / risk you see; prefer false "
        "positives over false negatives. End the verdict with 'ship' or "
        "'do not ship without resolving X'.\n\nTask: {task}"
    ),
    "reviewer": (
        "You are a review subagent. Read the provided change adversarially. "
        "List findings as: file:line, severity (info/warning/error), and a "
        "concrete suggested fix.\n\nTask: {task}"
    ),
    "refactorer": (
        "You are a refactor subagent. Improve the structure of the target "
        "without changing behavior. State explicitly which behaviors you "
        "preserve and how the refactor preserves them.\n\nTask: {task}"
    ),
    "custom": "{task}",
}


class SubAgentSpec(BaseModel):
    """The job description for one subagent."""

    name: str
    role: SubAgentRole = "custom"
    task: str
    skills: list[str] = Field(default_factory=list)  # overrides _ROLE_SKILLS
    files: list[str] = Field(default_factory=list)   # narrow file scope
    extra_notes: list[str] = Field(default_factory=list)
    mode: str = ""  # "reason" | "generate" (defaults from role)
    max_tokens: int | None = None
    provider: str | None = None  # let each subagent run on its own model
    model: str | None = None
    timeout_seconds: float = 180.0


class SubAgentResult(BaseModel):
    """The outcome of running one subagent."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    role: SubAgentRole
    task: str
    mode: str
    plan: str = ""
    tradeoffs: str = ""
    verdict: str = ""
    code: str = ""
    defense: str = ""
    usage: Usage = Field(default_factory=Usage)
    duration_seconds: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def summary(self) -> str:
        """A one-line readout suitable for the UI."""
        if self.error:
            return f"error: {self.error[:80]}"
        if self.mode == "generate" and self.code:
            return self.code.splitlines()[0][:80] if self.code else self.verdict[:80]
        # reason mode (or empty code): show first plan line or verdict
        first_plan_line = self.plan.splitlines()[0] if self.plan else ""
        return (first_plan_line or self.verdict)[:80]


def _build_subagent_context(
    spec: SubAgentSpec, *, parent_context: Context, project_cwd: Path
) -> Context:
    """Build a focused context for one subagent.

    Inherits parent skills (unless overridden), parent notes, and parent
    diffs. Narrows the repo file set to `spec.files` if provided —
    otherwise inherits the parent's repo files too.
    """
    ctx = Context()

    # Skills: spec override > role default > parent's
    if spec.skills:
        ctx.with_skills(spec.skills)
    elif _ROLE_SKILLS.get(spec.role):
        ctx.with_skills(_ROLE_SKILLS[spec.role])
    else:
        # Inherit parent's skills.
        for s in parent_context.builtin_skills:
            ctx.builtin_skills.append(s.model_copy(deep=True))

    # Custom skills from the parent always propagate (project memory etc).
    for s in parent_context.custom_skills:
        ctx.custom_skills.append(s.model_copy(deep=True))

    # Notes propagate.
    ctx.notes.extend(parent_context.notes)
    for note in spec.extra_notes:
        ctx.add_note(note)

    # Diffs propagate.
    for d in parent_context.diffs:
        ctx.diffs.append(d.model_copy(deep=True))

    # Repo files: narrow to `spec.files` when given.
    if spec.files:
        for rel in spec.files:
            p = project_cwd / rel
            if not p.is_file():
                continue
            try:
                content = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if len(content) > 100_000:
                content = content[:100_000] + "\n... (truncated)"
            ctx.repo_files.append(RepoFile(path=rel, content=content))
    else:
        for f in parent_context.repo_files:
            ctx.repo_files.append(f.model_copy(deep=True))

    return ctx


def _resolve_mode(spec: SubAgentSpec) -> str:
    if spec.mode in {"reason", "generate"}:
        return spec.mode
    return _ROLE_MODE.get(spec.role, "reason")


def _framed_task(spec: SubAgentSpec) -> str:
    template = _ROLE_FRAMING.get(spec.role, "{task}")
    return template.format(task=spec.task)


def run_subagent(
    spec: SubAgentSpec,
    *,
    parent_context: Context,
    project_cwd: Path | str | None = None,
    parent_provider: str = "openrouter",
    parent_model: str = "openai/gpt-4o-mini",
    api_key: str | None = None,
) -> SubAgentResult:
    """Run one subagent end-to-end. Catches exceptions and surfaces them
    on the result rather than crashing the parent."""
    cwd = Path(project_cwd) if project_cwd else Path.cwd()
    ctx = _build_subagent_context(spec, parent_context=parent_context, project_cwd=cwd)

    mode = _resolve_mode(spec)
    framed = _framed_task(spec)
    provider = spec.provider or parent_provider
    model = spec.model or parent_model

    start = time.time()
    try:
        prov = build_provider(name=provider, api_key=api_key, model=model)
        rt = LiteRuntime(prov)
        if mode == "generate":
            g: Generation = generate(
                framed, context=ctx, _runtime=rt, max_tokens=spec.max_tokens
            )
            return SubAgentResult(
                name=spec.name,
                role=spec.role,
                task=spec.task,
                mode="generate",
                plan=g.reasoning.plan,
                tradeoffs=g.reasoning.tradeoffs,
                verdict=g.reasoning.verdict,
                code=g.code,
                defense=g.defense,
                usage=g.usage,
                duration_seconds=time.time() - start,
            )
        r: Reasoning = reason(
            framed, context=ctx, _runtime=rt, max_tokens=spec.max_tokens
        )
        return SubAgentResult(
            name=spec.name,
            role=spec.role,
            task=spec.task,
            mode="reason",
            plan=r.plan,
            tradeoffs=r.tradeoffs,
            verdict=r.verdict,
            usage=r.usage,
            duration_seconds=time.time() - start,
        )
    except Exception as e:  # noqa: BLE001
        return SubAgentResult(
            name=spec.name,
            role=spec.role,
            task=spec.task,
            mode=mode,
            duration_seconds=time.time() - start,
            error=f"{type(e).__name__}: {e}",
        )


def run_subagents_parallel(
    specs: list[SubAgentSpec],
    *,
    parent_context: Context,
    project_cwd: Path | str | None = None,
    parent_provider: str = "openrouter",
    parent_model: str = "openai/gpt-4o-mini",
    max_concurrency: int = 4,
    api_key: str | None = None,
    on_done=None,  # optional callback (SubAgentResult) -> None
) -> list[SubAgentResult]:
    """Run every subagent in parallel; return results in input order.

    `on_done` fires once per subagent as it completes — useful for UI
    progress (e.g., flipping a spinner to a check mark).
    """
    if not specs:
        return []
    results: list[SubAgentResult | None] = [None] * len(specs)

    def _worker(i: int, spec: SubAgentSpec) -> tuple[int, SubAgentResult]:
        r = run_subagent(
            spec,
            parent_context=parent_context,
            project_cwd=project_cwd,
            parent_provider=parent_provider,
            parent_model=parent_model,
            api_key=api_key,
        )
        return i, r

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(1, min(max_concurrency, len(specs)))
    ) as pool:
        future_to_idx = {
            pool.submit(_worker, i, spec): i for i, spec in enumerate(specs)
        }
        for fut in concurrent.futures.as_completed(future_to_idx):
            try:
                i, result = fut.result()
            except Exception as e:  # noqa: BLE001 - per-future safety
                i = future_to_idx[fut]
                result = SubAgentResult(
                    name=specs[i].name,
                    role=specs[i].role,
                    task=specs[i].task,
                    mode=_resolve_mode(specs[i]),
                    error=f"{type(e).__name__}: {e}",
                )
            results[i] = result
            if on_done is not None:
                try:
                    on_done(result)
                except Exception:  # noqa: BLE001 - UI must not break the pool
                    pass
    return [r for r in results if r is not None]


def aggregate_usage(results: list[SubAgentResult]) -> Usage:
    """Sum every subagent's Usage. Convenience for the main agent's
    cost ledger."""
    total = Usage()
    for r in results:
        total = total + r.usage
    return total


__all__ = [
    "SubAgentRole",
    "SubAgentSpec",
    "SubAgentResult",
    "run_subagent",
    "run_subagents_parallel",
    "aggregate_usage",
]
