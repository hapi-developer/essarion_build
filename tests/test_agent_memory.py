"""Tests for project memory."""

from __future__ import annotations

from pathlib import Path

from essarion_build import Context
from essarion_build.agent._memory import (
    Memory,
    inject_into_context,
    load_memory,
    memory_path_for,
)
from essarion_build.agent._project import init_project


def test_memory_path_per_project(tmp_path: Path) -> None:
    init_project(tmp_path)
    p = memory_path_for(tmp_path)
    assert p == tmp_path / ".essarion" / "memory.md"


def test_memory_path_global_fallback(tmp_path: Path, monkeypatch) -> None:
    """No `.essarion/` → falls back to ~/.essarion/memory.md."""
    monkeypatch.setenv("HOME", str(tmp_path))
    p = memory_path_for(tmp_path)
    assert p == tmp_path / ".essarion" / "memory.md"


def test_load_memory_creates_empty_when_missing(tmp_path: Path) -> None:
    init_project(tmp_path)
    memory = load_memory(tmp_path)
    assert memory.facts == []
    assert "Project memory" in memory.header


def test_add_fact_persists_round_trip(tmp_path: Path) -> None:
    init_project(tmp_path)
    memory = load_memory(tmp_path)
    memory.add_fact("Use Result types, not exceptions")
    memory.save()

    again = load_memory(tmp_path)
    assert "Use Result types, not exceptions" in again.facts


def test_add_fact_deduplicates_case_insensitive(tmp_path: Path) -> None:
    init_project(tmp_path)
    memory = load_memory(tmp_path)
    memory.add_fact("Use snake_case")
    memory.add_fact("use SNAKE_CASE")  # same fact, different case
    assert len(memory.facts) == 1


def test_forget_removes_matching_facts(tmp_path: Path) -> None:
    init_project(tmp_path)
    memory = load_memory(tmp_path)
    memory.add_fact("Use snake_case")
    memory.add_fact("Use camelCase in TS")
    memory.add_fact("Prefer Result over panic")
    removed = memory.forget("camel")
    assert removed == 1
    assert any("snake_case" in f for f in memory.facts)
    assert any("Result" in f for f in memory.facts)


def test_clear_wipes_everything(tmp_path: Path) -> None:
    init_project(tmp_path)
    memory = load_memory(tmp_path)
    memory.add_fact("a")
    memory.add_fact("b")
    memory.clear()
    assert memory.facts == []


def test_inject_into_context_adds_custom_skill(tmp_path: Path) -> None:
    init_project(tmp_path)
    memory = load_memory(tmp_path)
    memory.add_fact("Production uses Postgres 16")

    ctx = Context()
    inject_into_context(memory, ctx)
    assert any(s.name == "memory" for s in ctx.custom_skills)
    body = ctx.to_prompt_block()
    assert "Production uses Postgres 16" in body


def test_inject_skips_when_empty(tmp_path: Path) -> None:
    """An empty memory file shouldn't inject noise into context."""
    memory = Memory(path=tmp_path / "m.md", header="", facts=[])
    ctx = Context()
    inject_into_context(memory, ctx)
    assert not any(s.name == "memory" for s in ctx.custom_skills)


def test_add_fact_rejects_empty(tmp_path: Path) -> None:
    import pytest

    memory = load_memory(tmp_path)
    with pytest.raises(ValueError):
        memory.add_fact("   ")


def test_forget_empty_pattern_is_no_op(tmp_path: Path) -> None:
    memory = load_memory(tmp_path)
    memory.add_fact("a")
    assert memory.forget("") == 0
    assert "a" in memory.facts
