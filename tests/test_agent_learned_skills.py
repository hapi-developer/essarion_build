"""Self-improving skills — the agent distills reusable, project-local skills
into `.essarion/skills/`, and the picker ranks them alongside the bundled ones
so the agent gets better at *this* codebase over time."""

from __future__ import annotations

from pathlib import Path

import pytest

from essarion_build.agent._learned_skills import (
    MAX_SKILL_CHARS,
    forget_learned_skill,
    learned_skills_dir,
    list_learned_skills,
    load_learned_skill,
    pool_bodies,
    save_learned_skill,
    slugify,
)


# ---------- slugify ----------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Add Migration!", "add_migration"),
        ("  multi   word--name ", "multi_word_name"),
        ("wire_a_new_tool", "wire_a_new_tool"),
        ("123 numbers", "123_numbers"),
    ],
)
def test_slugify(raw: str, expected: str) -> None:
    assert slugify(raw) == expected


def test_slugify_rejects_empty() -> None:
    with pytest.raises(ValueError):
        slugify("   ")
    with pytest.raises(ValueError):
        slugify("!!!")


def test_slugify_caps_length() -> None:
    assert len(slugify("word " * 40)) <= 48


# ---------- save / list / load / forget ----------

def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    (tmp_path / ".essarion").mkdir()
    path, created = save_learned_skill(tmp_path, "Add Migration", "- create a file under migrations/")
    assert created is True
    assert path == tmp_path / ".essarion" / "skills" / "add_migration.md"
    body = load_learned_skill(tmp_path, "add_migration")
    # A title is prepended when the author didn't supply one.
    assert body.lstrip().startswith("#")
    assert "migrations/" in body


def test_save_preserves_authored_title(tmp_path: Path) -> None:
    (tmp_path / ".essarion").mkdir()
    save_learned_skill(tmp_path, "auth_flow", "# Auth refresh gotcha\n- rotate before expiry")
    body = load_learned_skill(tmp_path, "auth_flow")
    assert body.lstrip().startswith("# Auth refresh gotcha")


def test_save_updates_in_place(tmp_path: Path) -> None:
    (tmp_path / ".essarion").mkdir()
    p1, created1 = save_learned_skill(tmp_path, "foo", "# Foo\n- one")
    p2, created2 = save_learned_skill(tmp_path, "foo", "# Foo\n- two")
    assert created1 is True
    assert created2 is False
    assert p1 == p2
    assert "two" in load_learned_skill(tmp_path, "foo")
    assert "one" not in load_learned_skill(tmp_path, "foo")


def test_list_is_sorted(tmp_path: Path) -> None:
    (tmp_path / ".essarion").mkdir()
    save_learned_skill(tmp_path, "zebra", "- z")
    save_learned_skill(tmp_path, "alpha", "- a")
    assert list_learned_skills(tmp_path) == ["alpha", "zebra"]


def test_forget(tmp_path: Path) -> None:
    (tmp_path / ".essarion").mkdir()
    save_learned_skill(tmp_path, "foo", "- one")
    assert forget_learned_skill(tmp_path, "foo") is True
    assert forget_learned_skill(tmp_path, "foo") is False
    assert list_learned_skills(tmp_path) == []


def test_rejects_secret_shaped_body(tmp_path: Path) -> None:
    (tmp_path / ".essarion").mkdir()
    with pytest.raises(ValueError, match="secret"):
        save_learned_skill(
            tmp_path, "leaky", "the prod key is sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        )


def test_rejects_empty_body(tmp_path: Path) -> None:
    (tmp_path / ".essarion").mkdir()
    with pytest.raises(ValueError):
        save_learned_skill(tmp_path, "foo", "   ")


def test_caps_size(tmp_path: Path) -> None:
    (tmp_path / ".essarion").mkdir()
    save_learned_skill(tmp_path, "big", "# Big\n" + "x" * (MAX_SKILL_CHARS * 2))
    assert len(load_learned_skill(tmp_path, "big")) <= MAX_SKILL_CHARS + 2


# ---------- pool / dir fallback ----------

def test_pool_bodies_empty_when_no_dir(tmp_path: Path) -> None:
    assert pool_bodies(tmp_path) == {}


def test_pool_bodies_returns_all(tmp_path: Path) -> None:
    (tmp_path / ".essarion").mkdir()
    save_learned_skill(tmp_path, "foo", "# Foo\n- one")
    save_learned_skill(tmp_path, "bar", "# Bar\n- two")
    pool = pool_bodies(tmp_path)
    assert set(pool) == {"foo", "bar"}
    assert "one" in pool["foo"]


def test_dir_is_under_project_essarion(tmp_path: Path) -> None:
    (tmp_path / ".essarion").mkdir()
    assert learned_skills_dir(tmp_path) == tmp_path / ".essarion" / "skills"


# ---------- picker integration ----------

def test_picker_ranks_a_learned_skill(tmp_path: Path) -> None:
    from essarion_build import list_skills
    from essarion_build.agent._skill_picker import explain_pick, pick_skills

    learned = {"add_migration": "# Add a migration\n- create a file under migrations/ then run migrate"}
    picks = pick_skills(
        "how do we add a database migration in this repo",
        available=list_skills() + list(learned),
        extra_bodies=learned,
    )
    assert "add_migration" in picks
    # explain_pick must tolerate (and describe) the learned skill too.
    why = explain_pick("add a database migration", picks, extra_bodies=learned)
    assert "add_migration" in why


def test_pick_skills_for_modes() -> None:
    from essarion_build.agent._loop import _pick_skills_for

    learned = {"deploy_here": "# Deploy\n- run scripts/release.sh then tag"}
    auto, _ = _pick_skills_for("how do I deploy here", "auto", learned=learned)
    assert "deploy_here" in auto
    all_picks, why = _pick_skills_for("anything", "all", learned=learned)
    assert "deploy_here" in all_picks
    assert "learned" in why
    none_picks, _ = _pick_skills_for("anything", "none", learned=learned)
    assert none_picks == []


# ---------- the distill_skill tool ----------

@pytest.fixture
def project(tmp_path: Path) -> Path:
    from essarion_build.agent._tools import bind_tools, register_all

    (tmp_path / ".essarion").mkdir()
    bind_tools(tmp_path)
    register_all()
    return tmp_path


def test_distill_skill_tool_writes_file(project: Path) -> None:
    from essarion_build.agent._tools import distill_skill

    out = distill_skill("Add Migration", "- create a file under migrations/")
    assert "distilled skill 'add_migration'" in out
    assert (project / ".essarion" / "skills" / "add_migration.md").is_file()


def test_distill_skill_tool_updates(project: Path) -> None:
    from essarion_build.agent._tools import distill_skill

    distill_skill("foo", "- one")
    out = distill_skill("foo", "- two")
    assert out.startswith("updated skill")


def test_distill_skill_rejects_empty(project: Path) -> None:
    from essarion_build.agent._tools import distill_skill

    with pytest.raises(ValueError):
        distill_skill("", "- body")
    with pytest.raises(ValueError):
        distill_skill("name", "   ")


def test_distill_skill_via_tool_registry(project: Path) -> None:
    from essarion_build import tools as sdk_tools

    out = sdk_tools.run_tools_in_plan(
        '<tool_call name="distill_skill">{"name": "wire_tool", '
        '"body": "- register the tool in register_all()"}</tool_call>',
        allow={"distill_skill"},
    )
    assert "skill" in out
    assert "wire_tool" in list_learned_skills(project)
