"""Evaluation harness: run a reasoning workflow against a labeled benchmark.

Why this matters: the moment you start tweaking prompts, context, or model
choice, you need a way to know whether the change improved things or just
moved them around. Vibes-based prompt engineering is how regressions ship.

A minimal eval has three parts:

1. **Cases** — a list of `EvalCase(task, expected, metadata)` records.
2. **Runner** — a callable that takes `(task)` and returns `(generated_text)`.
   Usually `lambda t: reason(t, context=ctx).verdict`, or similar.
3. **Scorer** — a callable that takes `(generated, expected, case)` and
   returns a `Score(passed, score, message)`.

`run_eval(cases, runner, scorer)` ties them together and returns a
`Report` with per-case results, aggregate pass rate, and total token
usage (when the runner reports it). Compare two `Report`s with
`Report.delta(other)` to see regression vs. improvement.

Three scorers ship: `exact_match`, `contains_all`, `keyword_overlap`.
Roll your own — it's just a function.
"""

from __future__ import annotations

import statistics
from typing import Any, Callable

from pydantic import BaseModel, Field

from ._providers import Usage


class EvalCase(BaseModel):
    """One test case in an eval suite."""

    task: str
    expected: str = ""  # used by scorers; may be empty
    metadata: dict[str, Any] = Field(default_factory=dict)


class Score(BaseModel):
    """Result of scoring one case. `score` is a 0..1 float; `passed` mirrors `score >= 0.5`."""

    passed: bool
    score: float = 0.0
    message: str = ""


class CaseResult(BaseModel):
    """One row in the report."""

    case: EvalCase
    generated: str
    score: Score
    usage: Usage = Field(default_factory=Usage)


class Report(BaseModel):
    """Aggregate result of a run."""

    name: str
    results: list[CaseResult]
    total_usage: Usage = Field(default_factory=Usage)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.score.passed)

    @property
    def failed(self) -> int:
        return len(self.results) - self.passed

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return self.passed / len(self.results)

    @property
    def mean_score(self) -> float:
        if not self.results:
            return 0.0
        return statistics.fmean(r.score.score for r in self.results)

    def delta(self, baseline: "Report") -> dict[str, Any]:
        """Diff this report against a baseline. Useful for CI gates.

        Returns {regressed: [task, ...], improved: [task, ...], pass_rate_delta,
        mean_score_delta, token_delta}.
        """
        base_by_task = {r.case.task: r.score for r in baseline.results}
        regressed: list[str] = []
        improved: list[str] = []
        for r in self.results:
            base = base_by_task.get(r.case.task)
            if base is None:
                continue
            if base.passed and not r.score.passed:
                regressed.append(r.case.task)
            elif not base.passed and r.score.passed:
                improved.append(r.case.task)
        return {
            "regressed": regressed,
            "improved": improved,
            "pass_rate_delta": self.pass_rate - baseline.pass_rate,
            "mean_score_delta": self.mean_score - baseline.mean_score,
            "token_delta": self.total_usage.total_tokens
            - baseline.total_usage.total_tokens,
        }

    def summary(self) -> str:
        return (
            f"{self.name}: {self.passed}/{len(self.results)} passed "
            f"({self.pass_rate:.0%}, mean score {self.mean_score:.2f}). "
            f"Tokens: {self.total_usage.total_tokens:,}."
        )


# ---- built-in scorers ----

def exact_match(generated: str, expected: str, case: EvalCase) -> Score:
    """Strict equality (after trimming)."""
    g = generated.strip()
    e = expected.strip()
    ok = g == e
    return Score(
        passed=ok,
        score=1.0 if ok else 0.0,
        message="match" if ok else f"expected {e!r}, got {g!r}",
    )


def contains_all(generated: str, expected: str, case: EvalCase) -> Score:
    """`expected` is interpreted as a comma-separated list of substrings that
    must all appear in `generated` (case-sensitive). Score is the fraction
    matched.
    """
    required = [s.strip() for s in expected.split(",") if s.strip()]
    if not required:
        return Score(passed=True, score=1.0, message="no requirements")
    hits = [s for s in required if s in generated]
    score = len(hits) / len(required)
    passed = len(hits) == len(required)
    return Score(
        passed=passed,
        score=score,
        message=(
            "all present"
            if passed
            else f"missing: {[s for s in required if s not in hits]}"
        ),
    )


def keyword_overlap(generated: str, expected: str, case: EvalCase) -> Score:
    """Jaccard similarity on whitespace-split tokens. Crude but useful for
    short generated answers."""
    g = set(generated.lower().split())
    e = set(expected.lower().split())
    if not e:
        return Score(passed=True, score=1.0, message="no expected tokens")
    overlap = g & e
    union = g | e
    score = len(overlap) / len(union) if union else 1.0
    return Score(
        passed=score >= 0.5,
        score=score,
        message=f"jaccard={score:.2f}",
    )


# ---- runner ----

Runner = Callable[[str], str]
RunnerWithUsage = Callable[[str], tuple[str, Usage]]
Scorer = Callable[[str, str, EvalCase], Score]


def run_eval(
    cases: list[EvalCase],
    runner: Runner | RunnerWithUsage,
    scorer: Scorer = contains_all,
    *,
    name: str = "eval",
) -> Report:
    """Run every case through `runner`, score with `scorer`, aggregate.

    The runner can return either a string (no usage tracking) or a
    `(string, Usage)` tuple (usage gets aggregated into the report).
    """
    results: list[CaseResult] = []
    total = Usage()
    for case in cases:
        out = runner(case.task)
        if isinstance(out, tuple):
            generated, usage = out
        else:
            generated, usage = out, Usage()
        score = scorer(generated, case.expected, case)
        results.append(
            CaseResult(case=case, generated=generated, score=score, usage=usage)
        )
        total = total + usage
    return Report(name=name, results=results, total_usage=total)


__all__ = [
    "EvalCase",
    "Score",
    "CaseResult",
    "Report",
    "Runner",
    "RunnerWithUsage",
    "Scorer",
    "exact_match",
    "contains_all",
    "keyword_overlap",
    "run_eval",
]
