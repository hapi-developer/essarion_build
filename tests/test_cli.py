"""Tests for the `essarion-build` CLI."""

from __future__ import annotations

import io
import json
import sys

import pytest

from essarion_build import LiteRuntime, StubProvider, __version__
from essarion_build.cli import build_parser, main


def test_cli_version(capsys: pytest.CaptureFixture) -> None:
    rc = main(["version"])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert out == __version__


def test_cli_skills_lists_all(capsys: pytest.CaptureFixture) -> None:
    rc = main(["skills"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "secure_coding" in out
    assert "testing" in out


def test_cli_skills_show_prints_body(capsys: pytest.CaptureFixture) -> None:
    rc = main(["skills", "--show", "secure_coding"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Validate at boundaries" in out


def test_cli_skills_show_unknown_returns_2(capsys: pytest.CaptureFixture) -> None:
    rc = main(["skills", "--show", "not_a_real_skill"])
    assert rc == 2


def test_cli_providers_lists_known(capsys: pytest.CaptureFixture) -> None:
    rc = main(["providers"])
    out = capsys.readouterr().out
    assert rc == 0
    for name in ["openrouter", "anthropic", "openai", "gemini", "ollama", "stub"]:
        assert name in out


def test_cli_estimate_with_repo(tmp_path, capsys: pytest.CaptureFixture) -> None:
    (tmp_path / "a.py").write_text("print('x')\n")
    rc = main(["estimate", "--repo", str(tmp_path), "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["repo_files"] == 1
    assert payload["estimated_tokens"] > 0


def test_cli_estimate_human(tmp_path, capsys: pytest.CaptureFixture) -> None:
    rc = main(["estimate"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Context size" in out


def test_cli_reason_with_stub_provider(tmp_path, capsys, monkeypatch) -> None:
    """End-to-end: `essarion-build reason "task" --provider stub` runs the loop
    against the stub provider."""

    # Wire the stub provider to scripted responses by monkey-patching
    # build_provider in the cli's namespace (it's imported as a function).
    stub = StubProvider(
        responses=[
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>preliminary</verdict>",
            "<verdict>final: ship</verdict>",
        ]
    )
    import essarion_build._runtime as rtmod

    original = rtmod.build_provider

    def fake_build(*, name, api_key, model):
        if name == "stub":
            return stub
        return original(name=name, api_key=api_key, model=model)

    monkeypatch.setattr(rtmod, "build_provider", fake_build)

    rc = main(
        ["reason", "task", "--provider", "stub", "--model", "stub-model", "--no-skills", "--json"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["verdict"] == "final: ship"


def test_cli_generate_with_stub_provider(monkeypatch, capsys) -> None:
    stub = StubProvider(
        responses=[
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
            "<code>def x(): pass</code>",
            "<verdict>ship</verdict><defense>safe</defense>",
        ]
    )
    import essarion_build._runtime as rtmod

    monkeypatch.setattr(
        rtmod,
        "build_provider",
        lambda *, name, api_key, model: stub if name == "stub" else rtmod.build_provider(
            name=name, api_key=api_key, model=model
        ),
    )

    rc = main(
        ["generate", "task", "--provider", "stub", "--model", "stub", "--no-skills", "--json"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["code"] == "def x(): pass"
    assert payload["defense"] == "safe"


def test_cli_reason_from_stdin(monkeypatch, capsys) -> None:
    stub = StubProvider(
        responses=[
            "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>p</verdict>",
            "<verdict>ship</verdict>",
        ]
    )
    import essarion_build._runtime as rtmod

    monkeypatch.setattr(
        rtmod,
        "build_provider",
        lambda *, name, api_key, model: stub if name == "stub" else rtmod.build_provider(
            name=name, api_key=api_key, model=model
        ),
    )

    monkeypatch.setattr("sys.stdin", io.StringIO("review the api"))
    rc = main(["reason", "-", "--provider", "stub", "--model", "x", "--no-skills"])
    assert rc == 0


def test_cli_unknown_subcommand_errors() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["doesnotexist"])


def test_cli_main_catches_exception_and_returns_1(monkeypatch, capsys) -> None:
    """Top-level exceptions become a non-zero exit code + stderr message."""

    def boom(args):
        raise RuntimeError("boom!")

    monkeypatch.setattr("essarion_build.cli.cmd_version", boom)
    rc = main(["version"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "boom!" in err
