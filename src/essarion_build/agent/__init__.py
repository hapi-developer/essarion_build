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
6. **Project folders.** Auto-detects the project root; per-project memory,
   config, and session storage in `<root>/.essarion/`.
7. **Background tasks.** /bg runs commands in parallel without blocking
   the agent; completion notices fire between turns.

Entry points:

- `essarion`           → interactive REPL (this module's `run_agent()`)
- `essarion <subcmd>`  → existing CLI subcommands (skills, reason, …)
"""

from ._memory import Memory, load_memory, memory_path_for
from ._project import Project, find_project_root, init_project
from ._session import Session, TaskTurn, estimate_cost_usd
from ._verify import VerifyResult, run_check
from .main import run_agent

__all__ = [
    # entry point
    "run_agent",
    # project
    "Project",
    "find_project_root",
    "init_project",
    # memory
    "Memory",
    "load_memory",
    "memory_path_for",
    # verify
    "VerifyResult",
    "run_check",
    # session
    "Session",
    "TaskTurn",
    "estimate_cost_usd",
]
