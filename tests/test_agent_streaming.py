"""Tests for the agent's streamed draft phase."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from essarion_build import (
    Context,
    ProviderResponse,
    StreamChunk,
    Usage,
)
from essarion_build._providers import _PROVIDER_REGISTRY
from essarion_build.agent import _loop, _ui
from essarion_build.agent._commands import dispatch
from essarion_build.agent._session import Session, new_session_id
from essarion_build.agent._theme import ESSARION_THEME


# A streaming provider that emits 3 small chunks per phase.
class _StreamingProvider:
    def __init__(self, *, api_key=None, model: str) -> None:
        self.model = model
        # Each phase's full response, split into chunks.
        self._phase_scripts = [
            # plan
            ["<plan>1. step</plan>", "<tradeoffs>- chosen: x</tradeoffs>", "<verdict>preliminary</verdict>"],
            # draft
            ["<code>def x():\n", "    return 42\n", "</code>"],
            # selfcheck
            ["<verdict>final: ship</verdict>", "<defense>", "ok</defense>"],
        ]
        self._idx = 0

    def complete(self, *, system, messages, max_tokens):
        # Fall-through for non-streaming consumers.
        text = "".join(self._phase_scripts[self._idx])
        self._idx += 1
        return ProviderResponse(text=text, usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15))

    def stream(self, *, system, messages, max_tokens):
        chunks = self._phase_scripts[self._idx]
        self._idx += 1
        for c in chunks:
            yield StreamChunk(text=c)
        yield StreamChunk(done=True, usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15))


@pytest.fixture
def streaming_session(tmp_path: Path) -> Session:
    return Session(
        id=new_session_id(),
        cwd=str(tmp_path),
        provider="streaming-test",
        model="m",
        stream=True,
        budget_usd=1.00,
        effort="standard",  # deterministic call count for the stub script
    )


@pytest.fixture
def headless_console() -> Console:
    buf = io.StringIO()
    return Console(theme=ESSARION_THEME, file=buf, force_terminal=False, width=120)


def _register_streaming():
    _PROVIDER_REGISTRY["streaming-test"] = lambda *, api_key=None, model: _StreamingProvider(
        api_key=api_key, model=model
    )


def _unregister_streaming():
    _PROVIDER_REGISTRY.pop("streaming-test", None)


def test_run_turn_with_streaming_writes_code_inline(
    headless_console, streaming_session, monkeypatch
) -> None:
    _register_streaming()
    try:
        monkeypatch.setattr(_ui, "prompt_approve_plan", lambda console: "approve")
        monkeypatch.setattr(_ui, "prompt_approve_apply", lambda console, kind="code": "discard")
        _loop.run_turn(headless_console, streaming_session, "do a thing")
        out = headless_console.file.getvalue()
        # Code text from streaming should appear inline.
        assert "def x" in out
        assert "return 42" in out
    finally:
        _unregister_streaming()


def test_run_turn_without_streaming_uses_spinner(
    headless_console, tmp_path, monkeypatch
) -> None:
    """When stream=False, we use the SpinnerStatus path; same result, no inline tokens."""
    _register_streaming()
    try:
        session = Session(
            id=new_session_id(),
            cwd=str(tmp_path),
            provider="streaming-test",
            model="m",
            stream=False,
            budget_usd=1.00,
            effort="standard",  # deterministic call count for the stub script
        )
        monkeypatch.setattr(_ui, "prompt_approve_plan", lambda console: "approve")
        monkeypatch.setattr(_ui, "prompt_approve_apply", lambda console, kind="code": "discard")
        _loop.run_turn(headless_console, session, "do a thing")
        out = headless_console.file.getvalue()
        # Code appears in the rendered panel (after the syntax-highlighted block)
        assert "def x" in out
        # streaming hint should NOT appear.
        assert "streaming…" not in out
    finally:
        _unregister_streaming()


def test_stream_command_toggle(headless_console, tmp_path) -> None:
    session = Session(
        id=new_session_id(),
        cwd=str(tmp_path),
        provider="openrouter",
        model="openai/gpt-4o-mini",
    )
    assert session.stream is False
    dispatch(headless_console, session, "/stream")
    assert session.stream is True
    dispatch(headless_console, session, "/stream")
    assert session.stream is False


def test_stream_command_explicit_on_off(headless_console, tmp_path) -> None:
    session = Session(
        id=new_session_id(),
        cwd=str(tmp_path),
        provider="openrouter",
        model="openai/gpt-4o-mini",
    )
    dispatch(headless_console, session, "/stream on")
    assert session.stream is True
    dispatch(headless_console, session, "/stream off")
    assert session.stream is False


def test_stream_command_bad_arg(headless_console, tmp_path) -> None:
    session = Session(
        id=new_session_id(),
        cwd=str(tmp_path),
        provider="openrouter",
        model="openai/gpt-4o-mini",
    )
    dispatch(headless_console, session, "/stream maybe")
    assert "usage" in headless_console.file.getvalue()
