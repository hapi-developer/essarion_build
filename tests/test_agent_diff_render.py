"""Tests for the pretty unified-diff renderer."""

from __future__ import annotations

import io

from rich.console import Console

from essarion_build.agent._diff_render import parse_unified_diff, render_diff_pretty
from essarion_build.agent._theme import ESSARION_THEME


SAMPLE = """--- a/src/foo.py
+++ b/src/foo.py
@@ -1,3 +1,4 @@
 def foo():
-    return 1
+    return 2
+    # added comment
--- a/src/bar.py
+++ b/src/bar.py
@@ -10,2 +10,1 @@
-x = 1
-y = 2
+x = 99
"""


def test_parse_unified_diff_splits_per_file() -> None:
    patches = parse_unified_diff(SAMPLE)
    assert len(patches) == 2
    assert patches[0].new_path == "src/foo.py"
    assert patches[1].new_path == "src/bar.py"


def test_parse_counts_additions_and_deletions() -> None:
    patches = parse_unified_diff(SAMPLE)
    assert patches[0].additions == 2
    assert patches[0].deletions == 1
    assert patches[1].additions == 1
    assert patches[1].deletions == 2


def test_render_diff_pretty_prints_each_file() -> None:
    buf = io.StringIO()
    console = Console(theme=ESSARION_THEME, file=buf, force_terminal=False, width=120)
    render_diff_pretty(console, SAMPLE)
    out = buf.getvalue()
    assert "src/foo.py" in out
    assert "src/bar.py" in out
    # Totals line.
    assert "2 file(s) changed" in out


def test_render_diff_pretty_handles_empty() -> None:
    buf = io.StringIO()
    console = Console(theme=ESSARION_THEME, file=buf, force_terminal=False, width=120)
    render_diff_pretty(console, "")
    assert "no changes" in buf.getvalue()


def test_render_diff_pretty_unparseable_falls_back() -> None:
    """If a diff has no file headers, we still print SOMETHING."""
    buf = io.StringIO()
    console = Console(theme=ESSARION_THEME, file=buf, force_terminal=False, width=120)
    render_diff_pretty(console, "just some random text\nnot a diff")
    out = buf.getvalue()
    # Either renders as a synthetic patch (no path) or prints the fallback.
    assert "random text" in out or "unparseable" in out
