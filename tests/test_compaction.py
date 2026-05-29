"""Tests for context compaction helpers."""

from __future__ import annotations

import pytest

from essarion_build import Context
from essarion_build._compaction import compact, keep_only_files, truncate_files


def _big_context() -> Context:
    ctx = Context().with_skill("scope_discipline")
    for i in range(10):
        ctx.repo_files.append(
            type(ctx.repo_files[0])(  # use the same class
                path=f"f{i}.py", content="x" * 1000
            ) if ctx.repo_files else __import__(
                "essarion_build._context", fromlist=["RepoFile"]
            ).RepoFile(path=f"f{i}.py", content="x" * 1000)
        )
    return ctx


def test_compact_no_op_when_under_budget() -> None:
    ctx = Context().with_skill("scope_discipline")
    before = ctx.estimate_tokens()
    out = compact(ctx, max_tokens=10_000)
    assert out.estimate_tokens() == before


def test_compact_drops_repo_files_first() -> None:
    from essarion_build._context import RepoFile

    ctx = Context().with_skill("scope_discipline").add_note("important note")
    for i in range(10):
        ctx.repo_files.append(RepoFile(path=f"f{i}.py", content="x" * 1000))

    # Estimated tokens ~ 2500+ for the files alone. Trim to a tiny budget.
    out = compact(ctx, max_tokens=500)
    assert len(out.repo_files) < 10
    # Skill and note preserved.
    assert any(s.name == "scope_discipline" for s in out.builtin_skills)
    assert out.notes == ["important note"]


def test_compact_keeps_high_signal_when_budget_too_small() -> None:
    """Even at an impossibly small budget, skills/notes/diffs are preserved."""
    from essarion_build._context import RepoFile

    ctx = (
        Context()
        .with_skill("secure_coding")
        .add_note("treat user input as hostile")
        .add_diff("--- a\n+++ b\n+x")
    )
    ctx.repo_files.append(RepoFile(path="huge.py", content="x" * 100_000))

    out = compact(ctx, max_tokens=10)
    assert any(s.name == "secure_coding" for s in out.builtin_skills)
    assert out.notes == ["treat user input as hostile"]
    assert out.diffs


def test_truncate_files_caps_content() -> None:
    from essarion_build._context import RepoFile

    ctx = Context()
    ctx.repo_files.append(RepoFile(path="big.py", content="x" * 5000))
    out = truncate_files(ctx, max_chars_per_file=200)
    f = out.repo_files[0]
    assert "truncated" in f.content
    assert len(f.content) < 400  # 200 head + marker


def test_truncate_leaves_small_files_unchanged() -> None:
    from essarion_build._context import RepoFile

    ctx = Context()
    ctx.repo_files.append(RepoFile(path="small.py", content="ok"))
    out = truncate_files(ctx, max_chars_per_file=200)
    assert out.repo_files[0].content == "ok"


def test_keep_only_files_matching_pattern() -> None:
    from essarion_build._context import RepoFile

    ctx = Context()
    for path in ["src/auth/login.py", "src/auth/jwt.py", "src/billing/pay.py"]:
        ctx.repo_files.append(RepoFile(path=path, content="..."))
    out = keep_only_files(ctx, patterns=["src/auth/*"])
    paths = {f.path for f in out.repo_files}
    assert paths == {"src/auth/login.py", "src/auth/jwt.py"}
