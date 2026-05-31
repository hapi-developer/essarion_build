"""The reducer + expectation checker — the model-free heart of computer-use,
tested with synthetic event streams (no browser, fully deterministic)."""

from __future__ import annotations

from essarion_build.computer._events import ObservedEvent
from essarion_build.computer._expectations import (
    check_expectation,
    parse_expectation,
)
from essarion_build.computer._reducer import reduce_events


def _ev(kind, summary, severity="info", ts=0.0, **detail):
    return ObservedEvent(kind=kind, summary=summary, severity=severity, ts=ts, detail=detail)


def test_bursts_of_identical_events_collapse_with_count() -> None:
    events = [_ev("dom", "subtree modified in <main>", ts=i) for i in range(50)]
    d = reduce_events(events)
    assert "×50" in d.text
    assert d.text.count("\n") == 0  # one merged line
    assert d.n_events == 50 and d.n_groups == 1


def test_errors_float_to_the_top_and_set_flag() -> None:
    events = [
        _ev("dom", "minor mutation", ts=1),
        _ev("network", "GET /api/users 200", ts=2),
        _ev("console", "TypeError: x is not a function", severity="error", ts=3),
    ]
    d = reduce_events(events)
    assert d.had_errors is True
    assert d.text.splitlines()[0].startswith("[error]")
    assert "TypeError" in d.highlights[0]


def test_min_severity_filters_noise_but_never_hides_errors() -> None:
    noise = [_ev("dom", f"mutation {i}", ts=i) for i in range(5)]
    d = reduce_events(noise, min_severity="warn")
    # All info-level → filtering would empty it, so we keep the top one, not blind.
    assert d.text != ""
    witherr = noise + [_ev("console", "Uncaught ReferenceError", severity="error", ts=9)]
    d2 = reduce_events(witherr, min_severity="warn")
    assert d2.had_errors and "ReferenceError" in d2.text


def test_budget_caps_lines() -> None:
    events = [_ev("network", f"GET /api/item/{i} 200", severity="notice", ts=i) for i in range(40)]
    d = reduce_events(events, budget_lines=5)
    lines = d.text.splitlines()
    assert len(lines) <= 6  # 5 + the "… more" overflow line
    assert "more change-groups" in lines[-1]


def test_empty_stream_is_explicit() -> None:
    d = reduce_events([])
    assert d.text == "no significant change observed"
    assert d.is_meaningful() is False


# ---- expectation checking (the reason-deep / act-fast mechanism) ----

def test_expectation_url_navigation_met_and_unmet() -> None:
    exp = parse_expectation("clicking login navigates to /dashboard")
    assert exp.url_contains == ["/dashboard"]
    digest = reduce_events([_ev("navigation", "navigated", severity="notice")])
    assert check_expectation(exp, digest, url="https://app.test/dashboard").met
    res = check_expectation(exp, digest, url="https://app.test/login?error=1")
    assert res.verdict == "unmet" and "/dashboard" in res.reasons[0]


def test_expectation_text_appears() -> None:
    exp = parse_expectation('a "Logout" button appears')
    assert exp.text_appears == ["Logout"]
    d_yes = reduce_events([_ev("dom", "added button: Logout", severity="notice")])
    d_no = reduce_events([_ev("dom", "added button: Sign in", severity="notice")])
    assert check_expectation(exp, d_yes).met
    assert check_expectation(exp, d_no).verdict == "unmet"


def test_expectation_text_absent() -> None:
    exp = parse_expectation('the "Loading spinner" should disappear')
    assert exp.text_absent == ["Loading spinner"]
    still_there = reduce_events([_ev("dom", "Loading spinner still visible", severity="notice")])
    assert check_expectation(exp, still_there).verdict == "unmet"
    gone = reduce_events([_ev("dom", "content rendered", severity="notice")])
    assert check_expectation(exp, gone).met


def test_expectation_no_errors() -> None:
    exp = parse_expectation("submits the form with no console errors")
    assert exp.expects_no_errors
    clean = reduce_events([_ev("network", "POST /submit 200", severity="notice")])
    broken = reduce_events([_ev("console", "500 Internal Server Error", severity="error")])
    assert check_expectation(exp, clean).met
    assert check_expectation(exp, broken).verdict == "unmet"


def test_non_checkable_expectation_is_unclear() -> None:
    exp = parse_expectation("things look better")
    assert not exp.is_checkable()
    assert check_expectation(exp, reduce_events([])).verdict == "unclear"
