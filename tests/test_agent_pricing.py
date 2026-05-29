"""Tests for pre-flight cost prediction."""

from __future__ import annotations

from pathlib import Path

from essarion_build import Context
from essarion_build.agent._pricing import (
    estimate_input_cost_usd,
    estimate_turn_cost_usd,
    format_cost,
)


def test_estimate_input_cost_known_model() -> None:
    ctx = Context().with_skill("scope_discipline")
    tokens, cost = estimate_input_cost_usd(
        ctx, provider="openrouter", model="openai/gpt-4o-mini"
    )
    assert tokens > 0
    assert cost > 0
    # ~ tokens × $0.15/Mtok ; can't pin a precise value because skills vary.
    assert cost < 0.01  # a single skill is well under a penny


def test_estimate_input_cost_unknown_model_returns_zero() -> None:
    ctx = Context().with_skill("scope_discipline")
    tokens, cost = estimate_input_cost_usd(
        ctx, provider="fictional-p", model="fictional-m"
    )
    assert tokens > 0
    assert cost == 0.0


def test_estimate_turn_cost_three_calls() -> None:
    ctx = Context().with_skill("scope_discipline")
    tokens, cost = estimate_turn_cost_usd(
        ctx,
        provider="openrouter",
        model="openai/gpt-4o-mini",
        max_tokens=2000,
        n_calls=3,
    )
    # Three calls should cost roughly 3× the single-input cost plus output.
    single_tokens, single_cost = estimate_input_cost_usd(
        ctx, provider="openrouter", model="openai/gpt-4o-mini"
    )
    assert cost > 3 * single_cost  # because of completion cost
    assert tokens == single_tokens  # estimate_turn_cost_usd returns input only


def test_estimate_turn_cost_ollama_is_free() -> None:
    ctx = Context().with_skill("scope_discipline")
    _, cost = estimate_turn_cost_usd(
        ctx, provider="ollama", model="llama3.2", max_tokens=2000,
    )
    assert cost == 0.0


def test_format_cost_zero() -> None:
    assert format_cost(0.0) == "$0.00"


def test_format_cost_micro() -> None:
    assert "$0.0001" in format_cost(0.0001) or "$0.00010" in format_cost(0.0001)


def test_format_cost_small() -> None:
    assert format_cost(0.005) == "$0.0050"


def test_format_cost_normal() -> None:
    assert format_cost(0.42) == "$0.420"
