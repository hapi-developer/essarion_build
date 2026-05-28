"""Tests for the recipes module."""

from __future__ import annotations

from essarion_build import recipes


def test_every_recipe_returns_tuple_of_str_and_list() -> None:
    """All recipes obey the (task, skills) contract."""
    for name in recipes.list_recipes():
        fn = getattr(recipes, name)
        task, skills = fn("some target")
        assert isinstance(task, str) and task
        assert isinstance(skills, list)
        assert all(isinstance(s, str) and s for s in skills)


def test_recipe_includes_target() -> None:
    task, _ = recipes.audit_for_race_conditions("booking-flow")
    assert "booking-flow" in task


def test_recipe_skills_are_known() -> None:
    """Every recipe's skills must be loadable from the bundle."""
    from essarion_build import list_skills

    bundled = set(list_skills())
    for name in recipes.list_recipes():
        fn = getattr(recipes, name)
        _, skills = fn("x")
        unknown = set(skills) - bundled
        assert not unknown, f"{name} references unknown skills: {unknown}"


def test_list_recipes_excludes_helpers() -> None:
    names = recipes.list_recipes()
    assert "list_recipes" not in names


def test_recipe_count_is_meaningful() -> None:
    names = recipes.list_recipes()
    assert len(names) >= 8
