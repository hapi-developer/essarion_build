"""Tests for budget enforcement mid-turn."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from essarion_build import ProviderResponse, Usage
from essarion_build._providers import _PROVIDER_REGISTRY
from essarion_build.agent import _loop, _ui
from essarion_build.agent._session import Session, new_session_id
from essarion_build.agent._theme import ESSARION_THEME
from essarion_build.agent._tools import bind_tools


class _ExpensiveProvider:
    """Each call costs ~$0.30 (1M input tokens at $0.30/Mtok)."""

    _idx = 0
    _RESPONSES = [
        # plan
        "<plan>1. do</plan><tradeoffs>- x</tradeoffs><verdict>preliminary</verdict>",
        # selfcheck
        "<verdict>final: ship</verdict>",
        # draft (won't be reached if budget halts)
        "<code>def x(): pass</code>",
        "<verdict>ship</verdict><defense>ok</defense>",
    ]

    @classmethod
    def reset(cls):
        cls._idx = 0

    def __init__(self, *, api_key=None, model: str) -> None:
        self.model = model

    def complete(self, *, system, messages, max_tokens):
        text = _ExpensiveProvider._RESPONSES[_ExpensiveProvider._idx]
        _ExpensiveProvider._idx += 1
        return ProviderResponse(
            text=text,
            usage=Usage(prompt_tokens=1_000_000, completion_tokens=0, total_tokens=1_000_000),
        )


def test_budget_halts_before_draft_when_exceeded(monkeypatch, tmp_path: Path) -> None:
    """The plan phase costs >$0.30; budget=$0.10 → draft is skipped."""
    _ExpensiveProvider.reset()
    # gpt-4o-mini pricing: $0.15/Mtok in. Two calls = 2M tokens = $0.30
    _PROVIDER_REGISTRY["expensive"] = lambda *, api_key=None, model: _ExpensiveProvider(
        api_key=api_key, model=model
    )
    try:
        session = Session(
            id=new_session_id(),
            cwd=str(tmp_path),
            provider="openrouter",
            model="openai/gpt-4o-mini",
            budget_usd=0.10,  # too low for even one turn at expensive pricing
        )
        bind_tools(tmp_path)

        # Have to use the provider name we know has pricing in _PRICE_TABLE.
        # Use openrouter, but route via the expensive provider's class.
        # Need to install our class under the openrouter name temporarily:
        original = _PROVIDER_REGISTRY.get("openrouter")
        _PROVIDER_REGISTRY["openrouter"] = lambda *, api_key=None, model: _ExpensiveProvider(
            api_key=api_key, model=model
        )

        try:
            monkeypatch.setattr(_ui, "prompt_approve_plan", lambda c: "approve")
            monkeypatch.setattr(_ui, "prompt_approve_apply", lambda c, kind="code": "discard")

            buf = io.StringIO()
            console = Console(theme=ESSARION_THEME, file=buf, force_terminal=False, width=120)
            _loop.run_turn(console, session, "anything")

            out = buf.getvalue()
            assert "budget cap reached" in out
            # The draft phase wasn't called → only 2 provider calls happened.
            assert _ExpensiveProvider._idx == 2
        finally:
            if original is not None:
                _PROVIDER_REGISTRY["openrouter"] = original
            else:
                _PROVIDER_REGISTRY.pop("openrouter", None)
    finally:
        _PROVIDER_REGISTRY.pop("expensive", None)


def test_budget_not_enforced_when_zero(monkeypatch, tmp_path: Path) -> None:
    """budget_usd=0 means no cap. (Edge case: don't crash.)"""
    _ExpensiveProvider.reset()
    _PROVIDER_REGISTRY["expensive2"] = lambda *, api_key=None, model: _ExpensiveProvider(
        api_key=api_key, model=model
    )
    try:
        from essarion_build.agent._session import TaskTurn

        session = Session(
            id=new_session_id(),
            cwd=str(tmp_path),
            provider="openrouter",
            model="openai/gpt-4o-mini",
            budget_usd=0.00,
        )
        # _check_budget returns True for zero budget.
        buf = io.StringIO()
        console = Console(theme=ESSARION_THEME, file=buf, force_terminal=False, width=120)
        turn = TaskTurn(task="x", cost_usd=999.99)
        ok = _loop._check_budget(console, session, turn)
        assert ok is True
    finally:
        _PROVIDER_REGISTRY.pop("expensive2", None)
