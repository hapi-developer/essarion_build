"""Screen-diff observer — pure grid logic, tested with synthetic frames."""

from __future__ import annotations

from essarion_build.computer._screen import ScreenDiffer


def _solid(cols, rows, color=(0, 0, 0)):
    return [[color for _ in range(cols)] for _ in range(rows)]


def test_first_frame_is_baseline_no_events() -> None:
    d = ScreenDiffer(cols=8, rows=6)
    assert d.events(_solid(8, 6)) == []


def test_detects_a_changed_block() -> None:
    d = ScreenDiffer(cols=8, rows=6, threshold=24)
    d.events(_solid(8, 6, (0, 0, 0)))  # baseline (black)
    g = _solid(8, 6, (0, 0, 0))
    # Paint a 2x2 white block at cols 2-3, rows 1-2.
    for r in (1, 2):
        for c in (2, 3):
            g[r][c] = (255, 255, 255)
    evs = d.events(g)
    assert len(evs) == 1
    e = evs[0]
    assert e.kind == "screen" and e.source == "desktop"
    assert e.detail["bbox"] == [2, 1, 3, 2]
    assert e.detail["cells"] == 4


def test_two_disjoint_changes_are_separate_regions() -> None:
    d = ScreenDiffer(cols=10, rows=10, threshold=24)
    d.events(_solid(10, 10))
    g = _solid(10, 10)
    g[0][0] = (255, 255, 255)          # top-left
    g[9][9] = (255, 255, 255)          # bottom-right
    evs = d.events(g)
    assert len(evs) == 2


def test_subthreshold_change_is_ignored() -> None:
    d = ScreenDiffer(cols=4, rows=4, threshold=30)
    d.events(_solid(4, 4, (100, 100, 100)))
    g = _solid(4, 4, (115, 115, 115))  # delta 15 < 30
    assert d.events(g) == []


def test_pixel_center_when_screen_size_known() -> None:
    d = ScreenDiffer(cols=10, rows=10, threshold=24, screen_size=(1000, 800))
    d.events(_solid(10, 10))
    g = _solid(10, 10)
    g[5][5] = (255, 255, 255)
    e = d.events(g)[0]
    # cell (5,5) center → ~ (550, 440) px
    cx, cy = e.detail["center"]
    assert 500 <= cx <= 600 and 400 <= cy <= 480
    assert "px" in e.summary


def test_large_change_is_notice_severity() -> None:
    d = ScreenDiffer(cols=10, rows=10, threshold=24)
    d.events(_solid(10, 10, (0, 0, 0)))
    evs = d.events(_solid(10, 10, (255, 255, 255)))  # whole screen flips
    assert evs[0].severity == "notice"
    assert evs[0].detail["frac"] == 1.0
