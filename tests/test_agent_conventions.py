"""Tests for project convention loading (AGENTS.md and friends)."""

from __future__ import annotations

from essarion_build import Context
from essarion_build.agent._conventions import (
    discover_convention_files,
    inject_into_context,
    load_conventions,
)


def test_no_conventions_returns_empty(tmp_path):
    (tmp_path / ".git").mkdir()  # project marker, but no rule files
    assert load_conventions(tmp_path) == ""


def test_loads_agents_md(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "AGENTS.md").write_text("Always run the tests before finishing.")
    body = load_conventions(tmp_path)
    assert "Always run the tests" in body
    assert "AGENTS.md" in body  # labelled by source


def test_agents_md_nesting_nearest_wins(tmp_path):
    (tmp_path / ".git").mkdir()  # makes tmp_path the project root
    (tmp_path / "AGENTS.md").write_text("Root rule: use tabs.")
    sub = tmp_path / "pkg"
    sub.mkdir()
    (sub / "AGENTS.md").write_text("Pkg rule: use four spaces.")
    body = load_conventions(sub)
    assert "Root rule" in body and "Pkg rule" in body
    # Nearest (pkg) is concatenated last so it refines/overrides the root.
    assert body.index("Root rule") < body.index("Pkg rule")
    assert "pkg/AGENTS.md" in body


def test_single_file_formats_picked_up(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "CLAUDE.md").write_text("Be concise.")
    (tmp_path / ".cursorrules").write_text("No global state.")
    body = load_conventions(tmp_path)
    assert "Be concise." in body
    assert "No global state." in body


def test_agents_md_listed_first(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "AGENTS.md").write_text("a")
    (tmp_path / "CLAUDE.md").write_text("c")
    names = [f.name for f in discover_convention_files(tmp_path)]
    assert names[0] == "AGENTS.md"
    assert "CLAUDE.md" in names


def test_large_file_is_capped(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "AGENTS.md").write_text("x" * 20_000)
    body = load_conventions(tmp_path)
    assert "truncated" in body
    assert len(body) < 13_000


def test_inject_into_context(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "AGENTS.md").write_text("House rule: prefer Result types.")
    ctx = Context()
    assert inject_into_context(tmp_path, ctx) is True
    assert "House rule: prefer Result types." in ctx.to_prompt_block()


def test_inject_returns_false_when_empty(tmp_path):
    (tmp_path / ".git").mkdir()
    assert inject_into_context(tmp_path, Context()) is False
