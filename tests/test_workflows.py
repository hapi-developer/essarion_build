"""Tests for high-level workflows (review, fix_bug, write_tests, refactor, docs)."""

from __future__ import annotations

from essarion_build import Context, LiteRuntime, StubProvider, Usage
from essarion_build import workflows


def _make_stub_review() -> StubProvider:
    return StubProvider(
        responses=[
            "<plan>1. nit A\n2. major B</plan>"
            "<tradeoffs>- chosen: flag both</tradeoffs>"
            "<verdict>do not ship without resolving B</verdict>",
            "<verdict>do not ship without resolving B</verdict>",
        ]
    )


def _make_stub_generate() -> StubProvider:
    return StubProvider(
        responses=[
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
            "<code>def x(): pass</code>",
            "<verdict>ship</verdict><defense>safe</defense>",
        ]
    )


def _patch_reason(monkeypatch, rt: LiteRuntime) -> None:
    from essarion_build import workflows as wf

    def fake_reason(task, **kwargs):
        kwargs["_runtime"] = rt
        from essarion_build._reasoning import reason as real_reason

        return real_reason(task, **kwargs)

    monkeypatch.setattr(wf, "reason", fake_reason)


def _patch_generate(monkeypatch, rt: LiteRuntime) -> None:
    from essarion_build import workflows as wf

    def fake_generate(task, **kwargs):
        kwargs["_runtime"] = rt
        from essarion_build._generate import generate as real_generate

        return real_generate(task, **kwargs)

    monkeypatch.setattr(wf, "generate", fake_generate)


def test_review_workflow(monkeypatch) -> None:
    stub = _make_stub_review()
    rt = LiteRuntime(stub)
    _patch_reason(monkeypatch, rt)
    r = workflows.review("src/foo.py")
    assert "major B" in r.plan
    assert "do not ship" in r.verdict
    # The review workflow should add the review skills.
    first_call_system = stub.calls[0]["system"]
    assert "code_review" in first_call_system
    assert "secure_coding" in first_call_system


def test_fix_bug_workflow(monkeypatch) -> None:
    stub = _make_stub_generate()
    rt = LiteRuntime(stub)
    _patch_generate(monkeypatch, rt)
    g = workflows.fix_bug("payment hangs on null email")
    assert "def x" in g.code
    first_call_system = stub.calls[0]["system"]
    assert "debugging" in first_call_system


def test_write_tests_workflow(monkeypatch) -> None:
    stub = _make_stub_generate()
    rt = LiteRuntime(stub)
    _patch_generate(monkeypatch, rt)
    g = workflows.write_tests("parse_jwt")
    assert "def x" in g.code
    assert "testing" in stub.calls[0]["system"]


def test_refactor_workflow(monkeypatch) -> None:
    stub = _make_stub_generate()
    rt = LiteRuntime(stub)
    _patch_generate(monkeypatch, rt)
    g = workflows.refactor("god class UserService")
    assert "def x" in g.code
    assert "refactoring" in stub.calls[0]["system"]


def test_docs_workflow(monkeypatch) -> None:
    stub = _make_stub_generate()
    rt = LiteRuntime(stub)
    _patch_generate(monkeypatch, rt)
    g = workflows.docs("public Context API")
    assert "def x" in g.code
    assert "documentation" in stub.calls[0]["system"]


def test_review_with_diff_includes_diff_section(monkeypatch) -> None:
    stub = _make_stub_review()
    rt = LiteRuntime(stub)
    _patch_reason(monkeypatch, rt)
    workflows.review("the diff", diff="--- a/x\n+++ b/x\n+new")
    assert "<diffs>" in stub.calls[0]["system"]
    assert "+new" in stub.calls[0]["system"]


def test_review_with_existing_context_does_not_duplicate_skills(monkeypatch) -> None:
    stub = _make_stub_review()
    rt = LiteRuntime(stub)
    _patch_reason(monkeypatch, rt)
    ctx = Context().with_skill("code_review")
    workflows.review("foo", context=ctx)
    names = [s.name for s in ctx.builtin_skills]
    # code_review must appear once (not duplicated) plus the other defaults.
    assert names.count("code_review") == 1
