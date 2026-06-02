"""Integration tests: repo map + conventions get injected into the turn context."""

from __future__ import annotations

import io

from rich.console import Console

from essarion_build import Context
from essarion_build.agent import _loop
from essarion_build.agent._session import Session, new_session_id


def _session(cwd) -> Session:
    return Session(
        id=new_session_id(), cwd=str(cwd), provider="stub", model="m",
        budget_usd=1.0, effort="quick", autonomous=True, skills_mode="none",
    )


def test_inject_repo_map_adds_note(tmp_path):
    (tmp_path / "svc.py").write_text(
        "def handler():\n    return compute()\n\ndef compute():\n    return 1\n"
    )
    ctx = Context()
    _loop._inject_repo_map(tmp_path, ctx, focus=[])
    block = ctx.to_prompt_block()
    assert "repo map" in block and "svc.py" in block


def test_inject_repo_map_disabled_by_config(tmp_path):
    (tmp_path / "svc.py").write_text("def handler():\n    return 1\n")
    ess = tmp_path / ".essarion"
    ess.mkdir()
    (ess / "config.toml").write_text("[agent]\nrepo_map = false\n")
    ctx = Context()
    _loop._inject_repo_map(tmp_path, ctx, focus=[])
    assert "repo map" not in ctx.to_prompt_block()


def test_build_context_injects_map_and_conventions(tmp_path):
    (tmp_path / ".git").mkdir()  # project root marker
    (tmp_path / "svc.py").write_text("def handler():\n    return 1\n")
    (tmp_path / "AGENTS.md").write_text("House rule: always write docstrings.")
    console = Console(file=io.StringIO())
    ctx, _picks, _why = _loop._build_context(
        "improve svc.py", session=_session(tmp_path), cwd=tmp_path, console=console
    )
    block = ctx.to_prompt_block()
    assert "repo map" in block            # Aider-style skeleton injected
    assert "svc.py" in block
    assert "always write docstrings" in block  # AGENTS.md conventions injected
