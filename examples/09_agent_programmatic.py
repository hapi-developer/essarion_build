"""Programmatic agent — drive the same plan-first loop from Python.

When you want the agent's plan-first behavior in your own program (CI
script, custom UI, batch process), call into the agent module directly.
The CLI is just one consumer of this API.

Run with:
    OPENROUTER_API_KEY=... python examples/09_agent_programmatic.py
"""

from __future__ import annotations

from rich.console import Console

from essarion_build.agent._loop import run_turn
from essarion_build.agent._session import (
    Session,
    new_session_id,
)
from essarion_build.agent._tools import bind_tools
from essarion_build.agent._ui import make_console


def main() -> None:
    console = make_console()
    session = Session(
        id=new_session_id(),
        cwd="./",
        provider="openrouter",
        model="openai/gpt-4o-mini",
        escalate_model="anthropic/claude-sonnet-4-6",
        budget_usd=0.50,
        skills_mode="auto",
    )
    bind_tools(session.cwd)
    run_turn(console, session, "review src/essarion_build/_runtime.py for issues")
    console.print(
        f"\n[meta]Total: {session.total_usage.total_tokens:,} tokens · "
        f"${session.total_cost_usd:.4f}[/meta]"
    )


if __name__ == "__main__":
    main()
