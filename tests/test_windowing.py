"""Tests for semantic windowing (`_windowing`)."""

from __future__ import annotations

from essarion_build._windowing import (
    head_tail_window,
    smart_truncate,
    window_around_lines,
    window_around_pattern,
)


def test_small_text_unchanged() -> None:
    text = "line one\nline two\n"
    assert head_tail_window(text, max_chars=1000) == text
    assert smart_truncate(text, max_chars=1000) == text
    assert window_around_pattern(text, "two", max_chars=1000) == text


def test_head_tail_preserves_both_ends() -> None:
    body = "\n".join(f"line {i}" for i in range(1000))
    out = head_tail_window(body, max_chars=400)
    assert out != body
    assert "line 0" in out  # head survived
    assert "line 999" in out  # tail survived — the whole point
    assert "truncated" in out
    assert len(out) <= 400 + 80  # marker overhead only


def test_head_tail_respects_budget_roughly() -> None:
    body = "x" * 10_000
    out = head_tail_window(body, max_chars=500)
    # head + tail + a short marker; comfortably under 2x budget.
    assert len(out) < 700


def test_window_around_pattern_centers_on_hit_with_header() -> None:
    lines = [f"filler {i}" for i in range(200)]
    lines[100] = "def important_function(arg):"
    lines[105] = "    return SECRET_VALUE  # the match"
    body = "\n".join(lines)
    out = window_around_pattern(body, "SECRET_VALUE", max_chars=2000)
    assert "SECRET_VALUE" in out
    # The enclosing def header is pulled in for context.
    assert "def important_function" in out
    # Far-away filler is dropped.
    assert "filler 0" not in out
    assert "truncated" in out


def test_window_around_pattern_no_match_falls_back_to_head_tail() -> None:
    body = "\n".join(f"line {i}" for i in range(1000))
    out = window_around_pattern(body, "nonexistent-zzz", max_chars=400)
    assert "line 0" in out
    assert "line 999" in out


def test_window_around_pattern_bad_regex_falls_back() -> None:
    body = "\n".join(f"line {i}" for i in range(1000))
    out = window_around_pattern(body, "[unclosed", max_chars=400)
    assert "truncated" in out
    assert "line 999" in out


def test_window_around_lines_merges_adjacent() -> None:
    body = "\n".join(f"line {i}" for i in range(500))
    out = window_around_lines(body, [10, 12, 14], max_chars=4000, context=3)
    # Three nearby hits collapse into one contiguous window (no marker between).
    assert "line 10" in out and "line 14" in out
    assert out.count("@@") <= 2  # a single merged window header (maybe one above)


def test_smart_truncate_dispatches_on_pattern() -> None:
    lines = [f"line {i}" for i in range(1000)]
    lines[500] = "TARGET here"
    body = "\n".join(lines)
    with_pat = smart_truncate(body, max_chars=600, pattern="TARGET")
    assert "TARGET" in with_pat
    no_pat = smart_truncate(body, max_chars=600)
    assert "line 0" in no_pat and "line 999" in no_pat


def test_window_caps_at_max_chars() -> None:
    # Many spread-out matches must still respect the budget.
    lines = [f"match {i}" if i % 2 == 0 else f"line {i}" for i in range(2000)]
    body = "\n".join(lines)
    out = window_around_pattern(body, "match", max_chars=1000, context=2)
    assert len(out) <= 1000 + 80
