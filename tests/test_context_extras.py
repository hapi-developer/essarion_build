"""Tests for new Context features: include/exclude globs, add_file, custom
skills, diffs, notes, token estimation."""

from __future__ import annotations

import pytest

from essarion_build import Context, ContextError


def test_add_repo_include_glob(tmp_path) -> None:
    (tmp_path / "a.py").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "c.py").write_text("c")

    ctx = Context().add_repo(tmp_path, include=["*.py"])
    paths = {f.path for f in ctx.repo_files}
    assert paths == {"a.py", "c.py"}


def test_add_repo_exclude_glob(tmp_path) -> None:
    (tmp_path / "src.py").write_text("ok")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_foo.py").write_text("test")

    ctx = Context().add_repo(tmp_path, exclude=["tests/*"])
    paths = {f.path for f in ctx.repo_files}
    assert "src.py" in paths
    assert "tests/test_foo.py" not in paths


def test_add_repo_max_files(tmp_path) -> None:
    for i in range(20):
        (tmp_path / f"{i:02d}.py").write_text(str(i))
    ctx = Context().add_repo(tmp_path, max_files=5)
    assert len(ctx.repo_files) == 5
    # sorted order means we get the first five lexicographically
    assert {f.path for f in ctx.repo_files} == {f"{i:02d}.py" for i in range(5)}


def test_add_file(tmp_path) -> None:
    p = tmp_path / "thing.py"
    p.write_text("print(1)")
    ctx = Context().add_file(p)
    assert len(ctx.repo_files) == 1
    assert ctx.repo_files[0].content == "print(1)"


def test_add_file_missing_raises(tmp_path) -> None:
    with pytest.raises(ContextError):
        Context().add_file(tmp_path / "nope.py")


def test_with_custom_skill_appears_in_prompt() -> None:
    ctx = Context().with_custom_skill("house_style", "- snake_case everywhere")
    block = ctx.to_prompt_block()
    assert '<skill name="house_style" source="custom">' in block
    assert "snake_case" in block


def test_with_custom_skill_empty_raises() -> None:
    with pytest.raises(ContextError):
        Context().with_custom_skill("", "body")
    with pytest.raises(ContextError):
        Context().with_custom_skill("name", "  ")


def test_with_skills_dir(tmp_path) -> None:
    (tmp_path / "house_style.md").write_text("- be brief")
    (tmp_path / "deploy_rules.md").write_text("- ship behind a flag")
    (tmp_path / "notes.txt").write_text("ignored")

    ctx = Context().with_skills_dir(tmp_path)
    names = {s.name for s in ctx.custom_skills}
    assert names == {"house_style", "deploy_rules"}


def test_add_diff_in_block() -> None:
    ctx = Context().add_diff(
        "--- a/file.py\n+++ b/file.py\n@@\n+ x = 1", title="my_diff"
    )
    block = ctx.to_prompt_block()
    assert "<diffs>" in block
    assert '<diff title="my_diff">' in block
    assert "x = 1" in block


def test_add_diff_empty_raises() -> None:
    with pytest.raises(ContextError):
        Context().add_diff("   ")


def test_add_note() -> None:
    ctx = Context().add_note("Prefer pathlib over os.path here.")
    block = ctx.to_prompt_block()
    assert "<notes>" in block
    assert "Prefer pathlib" in block


def test_estimate_tokens_returns_positive() -> None:
    ctx = (
        Context()
        .with_custom_skill("x", "some body of content " * 100)
        .add_note("a note")
    )
    assert ctx.estimate_tokens() > 0
    assert ctx.total_chars() > 0


def test_empty_context_estimate_is_at_least_one() -> None:
    """estimate_tokens() must never return zero — that would mislead callers
    into thinking no budget is needed."""
    assert Context().estimate_tokens() >= 1


def test_context_merge_unions_all_sections() -> None:
    from essarion_build._context import RepoFile

    base = (
        Context()
        .with_skill("scope_discipline")
        .add_note("rule one")
    )
    base.repo_files.append(RepoFile(path="a.py", content="old"))

    other = (
        Context()
        .with_skill("testing")
        .add_note("rule two")
        .add_diff("--- a\n+++ b\n+x")
    )
    other.repo_files.append(RepoFile(path="b.py", content="b"))

    merged = base.merge(other)
    names = {s.name for s in merged.builtin_skills}
    assert names == {"scope_discipline", "testing"}
    assert merged.notes == ["rule one", "rule two"]
    assert len(merged.diffs) == 1
    assert {f.path for f in merged.repo_files} == {"a.py", "b.py"}


def test_context_merge_dedups_repo_files_by_path_newest_wins() -> None:
    from essarion_build._context import RepoFile

    base = Context()
    base.repo_files.append(RepoFile(path="a.py", content="OLD"))
    other = Context()
    other.repo_files.append(RepoFile(path="a.py", content="NEW"))

    merged = base.merge(other)
    assert len(merged.repo_files) == 1
    assert merged.repo_files[0].content == "NEW"


def test_diff_from_git_returns_diff_object(tmp_path) -> None:
    """Smoke test using a freshly init'd repo with one tracked change."""
    import shutil
    import subprocess

    import pytest

    from essarion_build import Diff

    if shutil.which("git") is None:
        pytest.skip("git not on PATH")

    # Init a tiny repo so we don't depend on the surrounding one's state.
    # Disable signing / hooks for this throwaway repo — the test only needs
    # working diffs, not commit authentication.
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True
    )
    (tmp_path / "x.py").write_text("a = 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    result = subprocess.run(
        ["git", "commit", "-q", "--no-verify", "-m", "init"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Sandboxed env forces commit signing — skip without failing.
        pytest.skip(f"git commit failed in sandbox: {result.stderr.strip()}")
    (tmp_path / "x.py").write_text("a = 2\n")

    d = Diff.from_git(cwd=tmp_path)
    assert "a = 2" in d.body
    assert d.title == "HEAD"
