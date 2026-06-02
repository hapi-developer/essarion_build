"""Tests for the pretty unified-diff renderer."""

from __future__ import annotations

import io

from rich.console import Console

from essarion_build.agent._diff_render import (
    _render_patch,
    parse_unified_diff,
    render_diff_pretty,
)
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


DELETED = "--- a/src/gone.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-a = 1\n-b = 2\n"


def test_deleted_file_panel_titled_by_real_path_not_dev_null() -> None:
    """A deleted file's panel should be TITLED by the file that went away, not by
    the `/dev/null` placeholder (the placeholder still appears in the diff body)."""
    patches = parse_unified_diff(DELETED)
    assert len(patches) == 1
    title = _render_patch(patches[0]).title
    assert "gone.py" in title
    assert "/dev/null" not in title


# A removed source line beginning with "-- " (a SQL/Lua/Haskell comment) renders
# as "--- ..." in a unified diff; an added "++ " line renders as "+++ ...". These
# must NOT be mistaken for file headers.
COMMENTY = (
    "--- a/q.sql\n"
    "+++ b/q.sql\n"
    "@@ -1,3 +1,3 @@\n"
    " SELECT 1;\n"
    "-- the old comment\n"
    "++ the new line\n"
    " SELECT 2;\n"
)


def test_content_lines_starting_with_dashes_are_not_misparsed_as_headers() -> None:
    patches = parse_unified_diff(COMMENTY)
    # One file — not split in two by the "-- " line.
    assert len(patches) == 1
    assert patches[0].new_path == "q.sql"
    # The "-- " line counts as a deletion and the "++ " line as an addition.
    assert patches[0].deletions == 1
    assert patches[0].additions == 1
