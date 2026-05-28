"""essarion build — CLI coding agent.

The agent is a thin shell over the essarion-build SDK that turns the
plan→draft→selfcheck loop into an interactive coding experience.

Edge over Claude Code / Codex / Aider:

1. **Plan-first interactivity.** The SDK's `reason()` runs first; the user
   sees the plan and can approve / edit / cancel before any code-generation
   call is paid for.
2. **Token-budget meter.** Live cost readout in the footer. Makes the
   amplification savings visible.
3. **Smart skill selection.** A tiny "picker" call chooses 3-5 relevant
   skills from the 54 bundled — instead of dumping all 54 into every call.
4. **Multi-model arbitrage.** Cheap model for plan + selfcheck; escalate
   to a stronger model only when selfcheck rejects.
5. **Reasoning-trace persistence.** Sessions saved to ~/.essarion/sessions/
   so you can replay, fork, share.

Entry points:

- `essarion`           → interactive REPL (this module's `run_agent()`)
- `essarion <subcmd>`  → existing CLI subcommands (skills, reason, …)
"""

from .main import run_agent

__all__ = ["run_agent"]
