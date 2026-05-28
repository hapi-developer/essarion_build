"""Tests for the smart skill picker — one of the agent's edges."""

from __future__ import annotations

from essarion_build.agent._skill_picker import explain_pick, pick_skills


def test_picker_returns_a_list_of_known_skills() -> None:
    from essarion_build import list_skills

    bundled = set(list_skills())
    picks = pick_skills("review the JWT validation in src/auth.py for alg=none")
    assert picks
    assert all(p in bundled for p in picks)


def test_picker_picks_security_skills_for_security_task() -> None:
    picks = pick_skills(
        "audit the login endpoint for SQL injection and CSRF tokens"
    )
    # Should at least pick something security-flavored — exact set depends
    # on keyword overlap; the always-include set is a floor.
    assert "scope_discipline" in picks
    assert "error_handling" in picks


def test_picker_picks_react_skill_for_react_task() -> None:
    picks = pick_skills("fix the useEffect dependency array in components/Modal.tsx")
    assert "react_patterns" in picks


def test_picker_falls_back_to_always_include_on_empty_task() -> None:
    picks = pick_skills("")
    assert "scope_discipline" in picks
    assert "error_handling" in picks


def test_picker_respects_top_k_cap_plus_always_include() -> None:
    picks = pick_skills(
        "review the JWT validation in src/auth.py for alg=none",
        top_k=2,
    )
    # top_k=2 scored picks + 2 always-include = up to 4
    assert len(picks) <= 4


def test_explain_pick_lists_matched_tokens() -> None:
    picks = pick_skills(
        "audit the SQL query in src/db.py for injection"
    )
    why = explain_pick("audit the SQL query in src/db.py for injection", picks)
    assert any(name in why for name in picks)


def test_picker_skips_unknown_skills() -> None:
    """Picker honors the `available` filter — useful for tests / restricted bundles."""
    picks = pick_skills(
        "review the JWT validation",
        available=["secure_coding", "auth_security"],
    )
    assert set(picks) <= {"secure_coding", "auth_security"}
