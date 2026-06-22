"""The `remember` tool — self-accumulating project memory: the agent persists
durable facts to `.essarion/memory.md` mid-run, and they come back in the
next turn's context."""

from __future__ import annotations

from pathlib import Path

import pytest

from essarion_build.agent._memory import load_memory
from essarion_build.agent._tools import bind_tools, register_all, remember


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / ".essarion").mkdir()
    bind_tools(tmp_path)
    register_all()
    return tmp_path


def test_remember_persists_a_fact(project: Path) -> None:
    out = remember("tests run with `pytest -q` from the repo root")
    assert out.startswith("remembered:")
    mem = load_memory(project)
    assert any("pytest -q" in f for f in mem.facts)
    assert (project / ".essarion" / "memory.md").is_file()


def test_remember_dedups(project: Path) -> None:
    remember("the API layer lives in src/api/")
    out = remember("the API layer lives in src/api/")
    assert "duplicate" in out
    assert sum("src/api/" in f for f in load_memory(project).facts) == 1


def test_remember_rejects_empty_and_secrets(project: Path) -> None:
    with pytest.raises(ValueError):
        remember("   ")
    with pytest.raises(ValueError, match="secret"):
        remember("the prod key is sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")


def test_remember_normalizes_whitespace_and_caps_length(project: Path) -> None:
    remember("a   fact\n  with   messy\nwhitespace")
    assert "a fact with messy whitespace" in load_memory(project).facts
    long = "x" * 500
    remember(long)
    assert all(len(f) <= 300 for f in load_memory(project).facts)


def test_remember_is_callable_via_tool_registry(project: Path) -> None:
    from essarion_build import tools as sdk_tools

    out = sdk_tools.run_tools_in_plan(
        '<tool_call name="remember">{"fact": "deploys go through scripts/release.sh"}</tool_call>',
        allow={"remember"},
    )
    assert "remembered" in out
    assert any("release.sh" in f for f in load_memory(project).facts)
