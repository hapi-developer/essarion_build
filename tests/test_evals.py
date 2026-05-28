"""Tests for the evaluation harness."""

from __future__ import annotations

from essarion_build.evals import (
    EvalCase,
    Report,
    Score,
    contains_all,
    exact_match,
    keyword_overlap,
    run_eval,
)
from essarion_build._providers import Usage


def test_exact_match() -> None:
    s = exact_match("ship", "ship", EvalCase(task="x"))
    assert s.passed
    assert s.score == 1.0

    s = exact_match("ship", "do not ship", EvalCase(task="x"))
    assert not s.passed
    assert s.score == 0.0


def test_contains_all_partial() -> None:
    s = contains_all("we want validate and encode", "validate, encode, normalize", EvalCase(task="x"))
    assert not s.passed
    assert 0 < s.score < 1
    assert "normalize" in s.message


def test_contains_all_full() -> None:
    s = contains_all("we validate, encode, and normalize", "validate, encode, normalize", EvalCase(task="x"))
    assert s.passed
    assert s.score == 1.0


def test_contains_all_no_requirements() -> None:
    s = contains_all("anything", "", EvalCase(task="x"))
    assert s.passed


def test_keyword_overlap() -> None:
    s = keyword_overlap("the quick brown fox", "the quick yellow fox", EvalCase(task="x"))
    # 3 overlap (the, quick, fox), 5 union → 0.6
    assert s.score > 0.5
    assert s.passed


def test_run_eval_aggregates_pass_count() -> None:
    cases = [
        EvalCase(task="a", expected="ship"),
        EvalCase(task="b", expected="do not ship"),
        EvalCase(task="c", expected="ship"),
    ]
    answers = {"a": "ship", "b": "ship", "c": "ship"}

    def runner(task: str) -> str:
        return answers[task]

    report = run_eval(cases, runner, exact_match, name="t")
    assert report.passed == 2
    assert report.failed == 1
    assert abs(report.pass_rate - 2 / 3) < 0.001
    assert "2/3" in report.summary()


def test_run_eval_tracks_usage() -> None:
    cases = [EvalCase(task="a", expected="x"), EvalCase(task="b", expected="x")]
    usages = [Usage(prompt_tokens=10, total_tokens=12), Usage(prompt_tokens=20, total_tokens=22)]

    def runner(task: str):
        return ("x", usages.pop(0))

    report = run_eval(cases, runner, exact_match)
    assert report.total_usage.total_tokens == 34


def test_report_delta_finds_regressions_and_improvements() -> None:
    baseline = Report(
        name="b",
        results=[
            type("CR", (), {})()  # we'll construct below
        ],
    ) if False else None
    # Build with real classes.
    from essarion_build.evals import CaseResult

    cases = [EvalCase(task=f"t{i}") for i in range(4)]
    baseline = Report(
        name="b",
        results=[
            CaseResult(case=cases[0], generated="", score=Score(passed=True, score=1.0)),
            CaseResult(case=cases[1], generated="", score=Score(passed=False, score=0.0)),
            CaseResult(case=cases[2], generated="", score=Score(passed=True, score=1.0)),
            CaseResult(case=cases[3], generated="", score=Score(passed=False, score=0.0)),
        ],
    )
    candidate = Report(
        name="c",
        results=[
            CaseResult(case=cases[0], generated="", score=Score(passed=False, score=0.0)),  # regression
            CaseResult(case=cases[1], generated="", score=Score(passed=True, score=1.0)),   # improvement
            CaseResult(case=cases[2], generated="", score=Score(passed=True, score=1.0)),   # stable pass
            CaseResult(case=cases[3], generated="", score=Score(passed=False, score=0.0)),  # stable fail
        ],
    )
    delta = candidate.delta(baseline)
    assert delta["regressed"] == ["t0"]
    assert delta["improved"] == ["t1"]


def test_report_summary_is_human_readable() -> None:
    cases = [EvalCase(task="a", expected="ship")]
    report = run_eval(cases, lambda t: "ship", exact_match, name="house_style")
    s = report.summary()
    assert "house_style" in s
    assert "1/1" in s


def test_empty_report_pass_rate_is_zero() -> None:
    report = Report(name="empty", results=[])
    assert report.pass_rate == 0.0
    assert report.mean_score == 0.0
    assert report.passed == 0
    assert report.failed == 0
