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
    # One-line summary of what the autonomous turn actually did (the executor's
    # <done> summary). Fed into the next turn's conversation memory so the agent
    # remembers what it built when the user asks a follow-up.
    summary: str = ""
    # The concrete actions taken this turn ("Created index.html", "Ran ls -l",
    # "Started Simple HTTP Server"), in order. Surfaced in the next turn's memory
    # so the agent can answer "what did you just do?" with specifics.
    actions: list[str] = Field(default_factory=list)
    # The agent's final task checklist for the turn (todo/doing/done items).
    todos: list[dict] = Field(default_factory=list)
    skills_used: list[str] = Field(default_factory=list)
    files_touched: list[str] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    cost_usd: float = 0.0
    escalated: bool = False
    effort: str = ""  # the reasoning depth actually used this turn
    ts_start: float = Field(default_factory=time.time)
    ts_end: float = 0.0


class Session(BaseModel):
    """A REPL session's full state."""

    id: str
    cwd: str
    provider: str
    model: str
    escalate_model: str | None = None  # set on /escalate or auto-pick
    # Cross-model "second opinion": an INDEPENDENT model (ideally a different
    # family, runs on `provider`) that red-teams each change before it lands —
    # seeing only the goal + the diff, so it's cheap. Where two models disagree
    # is where bugs hide. None → off. Set with /crosscheck.
    crosscheck_model: str | None = None
    stream: bool = False  # True → stream draft tokens to the console
    max_tokens: int = 4096
    # Spending cap in USD. 0.0 (the default) means NO cap — we just meter and
    # show tokens + cost. Set one with `/budget <amount>` to halt the turn when
    # projected spend would cross it.
    budget_usd: float = 0.0
    # Exploration budget: max read-only tool calls (read_file/grep/…) in a single
    # autonomous turn before the agent is pushed to stop gathering context and
    # produce its answer/changes. 0 means "use the executor default". Guards
    # against the "reads forever, answers never" budget-exhaustion failure.
    read_cap: int = 0
    # Cheap model used only for the throwaway triage/classification call when
    # effort='auto'. None → triage runs on the main model. Lets a run keep a
    # capable default for real reasoning while spending pennies on routing.
    triage_model: str | None = None
    skills_mode: str = "auto"  # "auto" | "all" | "none"
    # Reasoning depth. The agent defaults to "auto" — a tiny triage call
    # sizes each task and routes to quick/standard/deep. Cheap on easy
    # tasks, deep only when warranted.
    effort: str = "auto"  # "quick" | "standard" | "deep" | "max" | "auto"
    # Autonomous ("agentic") mode — the DEFAULT. The agent plans internally
    # (no approval gate), then drives the real disk tools (write/edit/delete/
    # run_shell + background) in a Claude-Code / Codex-style loop until the whole
    # task is done — creating many files, running commands, fixing failures —
    # instead of emitting one code blob to apply by hand. Switch to the classic
    # plan → approve → hand-apply flow with `/auto off` or `--plan-first`.
    autonomous: bool = True
    # Computer use (opt-in): allow the agent to drive a real browser/desktop via
    # the reactive computer-use tools. Never on by default; set by --computer-use,
    # /computer, or an unambiguous request. Implies autonomous execution.
    computer_use: bool = False
    # Desktop control (opt-in): drive the REAL machine's mouse/keyboard/screen.
    # Explicit opt-in only (--desktop / /desktop); never activated from phrasing.
    # Implies autonomous + computer-use machinery.
    desktop_control: bool = False
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


class SessionHit(BaseModel):
    """One matching turn found by :func:`search_sessions`."""

    session_id: str
    started_at: float = 0.0
    turn_index: int = 0  # 1-based position within the session
    task: str = ""
    snippet: str = ""
    score: int = 0


def _excerpt(text: str, terms: list[str], width: int = 180) -> str:
    """A window of `text` centered on the earliest matching term."""
    low = text.lower()
    pos = min(
        (low.find(t) for t in terms if low.find(t) >= 0),
        default=-1,
    )
    if pos < 0:
        return " ".join(text.split())[:width]
    start = max(0, pos - width // 3)
    end = min(len(text), start + width)
    chunk = " ".join(text[start:end].split())
    return ("…" if start > 0 else "") + chunk + ("…" if end < len(text) else "")


def search_sessions(
    query: str,
    *,
    sessions_dir: str | Path | None = None,
    limit: int = 20,
    include_global: bool = True,
) -> list[SessionHit]:
    """Full-text recall across saved sessions — the zero-dependency answer to
    "what did we decide / build / try before?".

    Scores each turn by how often the query's terms appear across its task,
    summary, plan, verdict, defense, and actions, then returns the best matches
    newest-first. Searches `sessions_dir` (the per-project dir, when given) and,
    by default, also the global `~/.essarion/sessions/` dir.
    """
    terms = [t for t in (query or "").lower().split() if t]
    if not terms:
        return []

    dirs: list[Path] = []
    if sessions_dir is not None:
        dirs.append(session_dir(sessions_dir))
    if include_global or sessions_dir is None:
        g = session_dir()
        if g not in dirs:
            dirs.append(g)

    seen: set[Path] = set()
    hits: list[SessionHit] = []
    for d in dirs:
        for p in d.glob("*.json"):
            if p in seen:
                continue
            seen.add(p)
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            sid = data.get("id") or p.stem
            started = data.get("started_at") or 0.0
            for i, turn in enumerate(data.get("history") or [], start=1):
                if not isinstance(turn, dict):
                    continue
                task = str(turn.get("task", ""))
                fields = [
                    task,
                    str(turn.get("summary", "")),
                    str(turn.get("plan", "")),
                    str(turn.get("verdict", "")),
                    str(turn.get("defense", "")),
                    " ".join(str(a) for a in (turn.get("actions") or [])),
                ]
                hay = "\n".join(fields).lower()
                score = sum(hay.count(t) for t in terms)
                if not score:
                    continue
                # A hit in the task line itself is the strongest signal.
                score += 3 * sum(task.lower().count(t) for t in terms)
                snippet_src = next(
                    (f for f in fields if any(t in f.lower() for t in terms)), task
                )
                hits.append(
                    SessionHit(
                        session_id=sid,
                        started_at=float(started),
                        turn_index=i,
                        task=task[:120],
                        snippet=_excerpt(snippet_src, terms),
                        score=score,
                    )
                )
    hits.sort(key=lambda h: (-h.score, -h.started_at, h.turn_index))
    return hits[:limit]
