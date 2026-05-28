"""Session state: budget, history, model selection, persistence.

Lives in memory during a REPL; persisted to ~/.essarion/sessions/ at
shutdown (and on /save). Keeping this small and obvious — the agent loop
reads/writes via this module, never via globals.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .._providers import Usage


# Approximate $/Mtok prices for the most common (provider, model) tuples
# the agent will pick from. Used to compute a live cost estimate from
# token counts. These move; we don't pretend they're authoritative.
# Format: {(provider, model_substring): (input_per_mtok, output_per_mtok)}.
_PRICE_TABLE: dict[tuple[str, str], tuple[float, float]] = {
    ("openrouter", "openai/gpt-4o-mini"): (0.15, 0.60),
    ("openrouter", "openai/gpt-4o"): (2.50, 10.00),
    ("openrouter", "anthropic/claude-sonnet-4"): (3.00, 15.00),
    ("openrouter", "anthropic/claude-haiku-4-5"): (0.80, 4.00),
    ("openai", "gpt-4o-mini"): (0.15, 0.60),
    ("openai", "gpt-4o"): (2.50, 10.00),
    ("anthropic", "claude-haiku-4-5"): (0.80, 4.00),
    ("anthropic", "claude-sonnet-4-6"): (3.00, 15.00),
    ("anthropic", "claude-opus-4-7"): (15.00, 75.00),
    ("anthropic", "claude-opus-4-8"): (15.00, 75.00),
    ("gemini", "gemini-2.0-flash"): (0.10, 0.40),
    ("gemini", "gemini-1.5-pro"): (1.25, 5.00),
    ("ollama", ""): (0.0, 0.0),  # local — free
}


def estimate_cost_usd(provider: str, model: str, usage: Usage) -> float:
    """Estimate the USD cost of a Usage given a provider/model.

    Returns 0.0 when we don't have a price for the model — the meter
    still works for known-priced calls without lying about unknown ones.
    """
    for (p, m_sub), (in_p, out_p) in _PRICE_TABLE.items():
        if p == provider and (m_sub == "" or m_sub in model):
            input_cost = (usage.prompt_tokens / 1_000_000) * in_p
            output_cost = (usage.completion_tokens / 1_000_000) * out_p
            return input_cost + output_cost
    return 0.0


class TaskTurn(BaseModel):
    """One user→agent exchange inside a session."""

    task: str
    plan: str = ""
    tradeoffs: str = ""
    verdict: str = ""
    code: str = ""
    defense: str = ""
    skills_used: list[str] = Field(default_factory=list)
    files_touched: list[str] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    cost_usd: float = 0.0
    escalated: bool = False
    ts_start: float = Field(default_factory=time.time)
    ts_end: float = 0.0


class Session(BaseModel):
    """A REPL session's full state."""

    id: str
    cwd: str
    provider: str
    model: str
    escalate_model: str | None = None  # set on /escalate or auto-pick
    max_tokens: int = 4096
    budget_usd: float = 1.00
    skills_mode: str = "auto"  # "auto" | "all" | "none"
    history: list[TaskTurn] = Field(default_factory=list)
    total_usage: Usage = Field(default_factory=Usage)
    total_cost_usd: float = 0.0
    started_at: float = Field(default_factory=time.time)

    def record(self, turn: TaskTurn) -> None:
        """Add a completed turn and roll its usage / cost into the totals."""
        turn.ts_end = time.time()
        self.history.append(turn)
        self.total_usage = self.total_usage + turn.usage
        self.total_cost_usd += turn.cost_usd

    def budget_remaining(self) -> float:
        return max(0.0, self.budget_usd - self.total_cost_usd)

    def budget_used_pct(self) -> float:
        if self.budget_usd <= 0:
            return 0.0
        return min(1.0, self.total_cost_usd / self.budget_usd)


def session_dir(custom: str | Path | None = None) -> Path:
    """Where we persist sessions.

    Pass `custom` (e.g. `<project>/.essarion/sessions/`) for per-project
    storage. Falls back to the global `~/.essarion/sessions/`.
    """
    p = Path(custom) if custom is not None else Path.home() / ".essarion" / "sessions"
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_session(
    session: Session, *, sessions_dir: str | Path | None = None
) -> Path:
    """Write the session to `<sessions_dir>/<id>.json`. Returns the path."""
    path = session_dir(sessions_dir) / f"{session.id}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(session.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def load_session(
    session_id: str, *, sessions_dir: str | Path | None = None
) -> Session:
    """Read a previously-saved session by id.

    If `sessions_dir` is supplied (the per-project dir) we look there
    first, then fall back to the global ~/.essarion/sessions/ dir.
    """
    candidates = []
    if sessions_dir is not None:
        candidates.append(session_dir(sessions_dir) / f"{session_id}.json")
    candidates.append(session_dir() / f"{session_id}.json")
    for path in candidates:
        if path.exists():
            return Session.model_validate_json(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"no session named {session_id!r}")


def list_sessions(sessions_dir: str | Path | None = None) -> list[dict[str, Any]]:
    """A list of saved session summaries (id, started_at, model, cost)."""
    out: list[dict[str, Any]] = []
    for p in sorted(session_dir(sessions_dir).glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append(
                {
                    "id": data.get("id"),
                    "started_at": data.get("started_at"),
                    "model": data.get("model"),
                    "cost_usd": data.get("total_cost_usd"),
                    "turns": len(data.get("history") or []),
                }
            )
        except (OSError, json.JSONDecodeError):
            continue
    return out


def new_session_id() -> str:
    """Short, sortable session ID: YYYYMMDD-HHMMSS-<rand>."""
    import secrets

    ts = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    return f"{ts}-{secrets.token_hex(2)}"
