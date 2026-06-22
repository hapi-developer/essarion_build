"""The `essarion-build review` subcommand — the CI surface that reviews a diff
and (uniquely) gets an INDEPENDENT cross-model second opinion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from essarion_build import StubProvider
from essarion_build.cli import _render_review_markdown, cmd_review, main

_DIFF = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old = 1\n+new = 2\n"


def _patch_provider(monkeypatch, stub) -> None:
    """Route both the reason() loop and the crosscheck to the same stub."""
    import essarion_build._providers as provmod
    import essarion_build._runtime as rtmod

    def fake(*, name, api_key, model):
        if name == "stub":
            return stub
        return rtmod.build_provider(name=name, api_key=api_key, model=model)

    monkeypatch.setattr(rtmod, "build_provider", fake)
    monkeypatch.setattr(provmod, "build_provider", fake)


def test_review_empty_diff(tmp_path: Path, capsys) -> None:
    p = tmp_path / "empty.diff"
    p.write_text("")
    rc = main(["review", "--diff", str(p)])
    assert rc == 0
    assert "no diff to review" in capsys.readouterr().out


def test_review_renders_markdown(monkeypatch, tmp_path: Path, capsys) -> None:
    stub = StubProvider(
        responses=[
            "<plan>x.py:1 — magic number, no validation</plan>"
            "<tradeoffs>-</tradeoffs><verdict>preliminary</verdict>",
            "<verdict>do not ship: validate input</verdict>",
        ]
    )
    _patch_provider(monkeypatch, stub)
    p = tmp_path / "d.diff"
    p.write_text(_DIFF)
    rc = main(["review", "--diff", str(p), "--provider", "stub", "--model", "x", "--no-skills"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "essarion-build review" in out
    assert "do not ship" in out


def test_review_with_crosscheck_json(monkeypatch, tmp_path: Path, capsys) -> None:
    stub = StubProvider(
        responses=[
            "<plan>looks fine</plan><tradeoffs>-</tradeoffs><verdict>ship</verdict>",
            "<verdict>ship</verdict>",
            # the independent second opinion:
            "<agree>no</agree>\n<concerns>\n- x.py:new — off-by-one on the bound\n"
            "</concerns>\n<summary>do-not-ship-until-bound-fixed</summary>",
        ]
    )
    _patch_provider(monkeypatch, stub)
    p = tmp_path / "d.diff"
    p.write_text(_DIFF)
    rc = main(
        [
            "review", "--diff", str(p), "--provider", "stub", "--model", "x",
            "--no-skills", "--crosscheck-model", "other-model", "--json",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["crosscheck"]["model"] == "other-model"
    assert payload["crosscheck"]["disagrees"] is True
    assert any("off-by-one" in c for c in payload["crosscheck"]["concerns"])


def test_review_fail_on_disagree_exit_code(monkeypatch, tmp_path: Path, capsys) -> None:
    stub = StubProvider(
        responses=[
            "<plan>ok</plan><tradeoffs>-</tradeoffs><verdict>ship</verdict>",
            "<verdict>ship</verdict>",
            "<agree>no</agree>\n<concerns>\n- a:b — broken\n</concerns>\n<summary>nope</summary>",
        ]
    )
    _patch_provider(monkeypatch, stub)
    p = tmp_path / "d.diff"
    p.write_text(_DIFF)
    rc = main(
        [
            "review", "--diff", str(p), "--provider", "stub", "--model", "x",
            "--no-skills", "--crosscheck-model", "other", "--fail-on-disagree",
        ]
    )
    assert rc == 3


# ---------- the markdown renderer ----------

def test_render_markdown_without_opinion() -> None:
    from types import SimpleNamespace

    r = SimpleNamespace(
        plan="finding here", verdict="ship", tradeoffs="",
        usage=SimpleNamespace(total_tokens=42),
    )
    md = _render_review_markdown(r, None)
    assert "essarion-build review" in md
    assert "finding here" in md
    assert "Cross-model second opinion" not in md


def test_render_markdown_with_disagreeing_opinion() -> None:
    from types import SimpleNamespace

    from essarion_build.agent._crosscheck import SecondOpinion

    r = SimpleNamespace(
        plan="ok", verdict="ship", tradeoffs="",
        usage=SimpleNamespace(total_tokens=10),
    )
    op = SecondOpinion(agree=False, concerns=["x.py:y — leak"], summary="fix it", model="m")
    md = _render_review_markdown(r, op)
    assert "Cross-model second opinion" in md
    assert "x.py:y — leak" in md
    assert "where they disagree is where bugs hide" in md
