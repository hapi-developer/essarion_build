"""Tests for the agent session: budget, cost estimation, persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from essarion_build import Usage
from essarion_build.agent._session import (
    Session,
    TaskTurn,
    estimate_cost_usd,
    list_sessions,
    load_session,
    new_session_id,
    save_session,
    session_dir,
)


def test_estimate_cost_known_model() -> None:
    cost = estimate_cost_usd(
        "openrouter", "openai/gpt-4o-mini",
        Usage(prompt_tokens=1_000_000, completion_tokens=500_000, total_tokens=1_500_000),
    )
    # 1M input @ $0.15 + 0.5M output @ $0.60 = $0.15 + $0.30 = $0.45
    assert abs(cost - 0.45) < 0.001


def test_estimate_cost_unknown_model_returns_zero() -> None:
    cost = estimate_cost_usd(
        "fictional-provider", "fictional-model",
        Usage(prompt_tokens=10_000, total_tokens=10_000),
    )
    assert cost == 0.0


def test_estimate_cost_ollama_is_free() -> None:
    cost = estimate_cost_usd(
        "ollama", "llama3.2",
        Usage(prompt_tokens=10_000_000, completion_tokens=5_000_000),
    )
    assert cost == 0.0


def test_session_budget_remaining_and_pct() -> None:
    s = Session(
        id="t", cwd="/tmp", provider="openrouter", model="openai/gpt-4o-mini",
        budget_usd=1.00,
    )
    s.total_cost_usd = 0.30
    assert abs(s.budget_remaining() - 0.70) < 1e-9
    assert abs(s.budget_used_pct() - 0.30) < 1e-9


def test_session_budget_remaining_clamped_at_zero() -> None:
    s = Session(
        id="t", cwd="/tmp", provider="openrouter", model="openai/gpt-4o-mini",
        budget_usd=1.00,
    )
    s.total_cost_usd = 2.00
    assert s.budget_remaining() == 0.0
    assert s.budget_used_pct() == 1.0


def test_session_record_aggregates() -> None:
    s = Session(
        id="t", cwd="/tmp", provider="openrouter", model="openai/gpt-4o-mini",
    )
    s.record(TaskTurn(
        task="x",
        usage=Usage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        cost_usd=0.01,
    ))
    s.record(TaskTurn(
        task="y",
        usage=Usage(prompt_tokens=200, completion_tokens=80, total_tokens=280),
        cost_usd=0.02,
    ))
    assert len(s.history) == 2
    assert s.total_usage.total_tokens == 430
    assert abs(s.total_cost_usd - 0.03) < 1e-9


def test_session_save_and_load_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    s = Session(
        id=new_session_id(),
        cwd="/tmp",
        provider="openrouter",
        model="openai/gpt-4o-mini",
    )
    s.record(TaskTurn(task="hello", usage=Usage(prompt_tokens=10)))
    path = save_session(s)
    assert path.exists()

    loaded = load_session(s.id)
    assert loaded.id == s.id
    assert len(loaded.history) == 1
    assert loaded.history[0].task == "hello"


def test_list_sessions_lists_saved(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    s = Session(
        id=new_session_id(),
        cwd="/tmp",
        provider="openrouter",
        model="openai/gpt-4o-mini",
    )
    save_session(s)
    listing = list_sessions()
    assert any(entry["id"] == s.id for entry in listing)


def test_new_session_id_is_unique() -> None:
    a = new_session_id()
    b = new_session_id()
    assert a != b
    assert len(a.split("-")) == 3


def test_session_defaults_to_autonomous() -> None:
    """Autonomous (agentic) mode is the DEFAULT: a bare session builds tasks
    end-to-end on disk in a loop, rather than the plan→approve→hand-apply flow."""
    s = Session(id="x", cwd=".", provider="stub", model="m")
    assert s.autonomous is True


def test_session_defaults_to_no_budget_cap() -> None:
    """No spending cap by default — we just meter tokens + cost. A cap is opt-in
    via `/budget` or --budget."""
    s = Session(id="x", cwd=".", provider="stub", model="m")
    assert s.budget_usd == 0.0
