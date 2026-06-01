"""Autonomous execution loop: the agent chains real disk tools (write/edit/
delete/shell) toward a goal until it emits <done>. Driven by scripted stub
responses so it's fully deterministic — no API key, no network."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from rich.console import Console

from essarion_build import Context, ProviderResponse, Usage
from essarion_build._providers import _PROVIDER_REGISTRY, StubProvider
from essarion_build._runtime import LiteRuntime
from essarion_build.agent import _agent_exec, _loop, _ui
from essarion_build.agent._session import Session, TaskTurn, new_session_id
from essarion_build.agent._theme import ESSARION_THEME
from essarion_build.agent._tools import bind_tools, register_all


def _call(name: str, **args: object) -> str:
    return f'<tool_call name="{name}">{json.dumps(args)}</tool_call>'


@pytest.fixture
def console() -> Console:
    return Console(theme=ESSARION_THEME, file=io.StringIO(), force_terminal=False, width=120)


@pytest.fixture
def session(tmp_path: Path) -> Session:
    bind_tools(tmp_path)
    register_all()
    return Session(
        id=new_session_id(),
        cwd=str(tmp_path),
        provider="stub",
        model="m",
        budget_usd=1.00,
        effort="quick",  # 1 plan call, deterministic
        autonomous=True,
    )


def test_execute_creates_edits_deletes_and_runs(console, session, tmp_path) -> None:
    """The loop should write a file, edit it, delete another, run a command,
    and report the files it touched — all directly on disk."""
    stub = StubProvider(responses=[
        _call("write_file", path="fib.py", content="def fib(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\n"),
        _call("write_file", path="junk.txt", content="scratch\n"),
        _call("apply_diff", path="fib.py", old="return a\n", new="return a  # nth fibonacci\n"),
        _call("delete_file", path="junk.txt"),
        _call("run_shell", cmd="echo built-ok"),
        "<done>created fib.py, edited it, removed junk.txt, verified</done>",
    ])
    turn = TaskTurn(task="build fib")
    result = _agent_exec.execute(
        console, session, "write fib.py with a test", Context(),
        make_runtime=lambda p, m: LiteRuntime(stub), turn=turn,
    )

    # On-disk effects.
    assert (tmp_path / "fib.py").is_file()
    assert "nth fibonacci" in (tmp_path / "fib.py").read_text()  # the edit landed
    assert not (tmp_path / "junk.txt").is_file()                 # created then deleted

    # Loop bookkeeping.
    assert result.stopped_reason == "done"
    assert "fib.py" in result.files_touched
    assert "junk.txt" in result.files_touched
    assert "created fib.py" in result.summary

    # Each action surfaced as a compact, faded action line (verb, not tool name).
    out = console.file.getvalue()
    for verb in ("Created", "Edited", "Deleted", "Ran"):
        assert verb in out, f"missing compact action line: {verb}"


def test_execute_respects_step_cap(console, session) -> None:
    """A model that never says <done> is stopped at the step cap, not forever."""
    stub = StubProvider(responses=[_call("list_dir", path=".")] * 50, auto_respond=False)
    # auto_respond=False but we give plenty; cap should bite before exhaustion.
    result = _agent_exec.execute(
        console, session, "loop forever", Context(),
        make_runtime=lambda p, m: LiteRuntime(stub), max_steps=5,
    )
    assert result.stopped_reason == "max_steps"
    assert result.steps == 5


class _AutoProvider:
    """Scripted provider for the full run_turn_autonomous path. Class-var queue
    persists across the agent rebuilding the provider each call."""

    _RESPONSES = [
        # plan phase (quick → 1 call, no tool_calls so no inline re-plan)
        "<plan>1. write greet.py\n2. wire a CLI</plan>"
        "<tradeoffs>pure function</tradeoffs><verdict>ship</verdict>",
        # autonomous exec
        _call("write_file", path="greet.py", content="def greet(name):\n    return f'hi {name}'\n"),
        _call("write_file", path="cli.py", content="from greet import greet\nprint(greet('world'))\n"),
        _call("run_shell", cmd="python cli.py"),
        "<done>greet.py + cli.py created and run</done>",
    ]
    _idx = 0

    @classmethod
    def reset(cls) -> None:
        cls._idx = 0

    def __init__(self, *, api_key=None, model: str) -> None:
        self.model = model

    def complete(self, *, system, messages, max_tokens):
        if _AutoProvider._idx >= len(_AutoProvider._RESPONSES):
            raise IndexError("script exhausted")
        text = _AutoProvider._RESPONSES[_AutoProvider._idx]
        _AutoProvider._idx += 1
        return ProviderResponse(text=text, usage=Usage(prompt_tokens=20, completion_tokens=10, total_tokens=30))


def test_run_turn_autonomous_end_to_end(monkeypatch, console, session, tmp_path) -> None:
    """Plan → approve → autonomous build, exercised through the public entry."""
    _AutoProvider.reset()
    monkeypatch.setitem(
        _PROVIDER_REGISTRY, "stub",
        lambda *, api_key=None, model: _AutoProvider(api_key=api_key, model=model),
    )
    monkeypatch.setattr(_ui, "prompt_approve_plan", lambda c: "approve")
    _loop.run_turn_autonomous(console, session, "write a greeting helper and a CLI")

    # The agent wrote both files directly to disk.
    assert (tmp_path / "greet.py").is_file()
    assert (tmp_path / "cli.py").is_file()

    # The turn recorded the plan and the files it touched.
    assert session.history, "turn not recorded"
    last = session.history[-1]
    assert "greet.py" in last.plan or "write greet.py" in last.plan
    assert "greet.py" in last.files_touched and "cli.py" in last.files_touched

    out = console.file.getvalue()
    # The compact action lines surfaced the work (no verbose tool dumps / panels).
    assert "Created" in out and "greet.py" in out
    assert last.summary  # the executor's <done> summary was stored for memory


def test_autonomous_turn_does_not_prompt_for_approval(
    monkeypatch, console, session, tmp_path
) -> None:
    """The default agentic turn plans internally and builds straight through —
    it must NOT stop to ask the user to approve the plan."""
    _AutoProvider.reset()
    monkeypatch.setitem(
        _PROVIDER_REGISTRY, "stub",
        lambda *, api_key=None, model: _AutoProvider(api_key=api_key, model=model),
    )

    def _boom(_console):
        raise AssertionError("autonomous mode must not prompt for plan approval")

    monkeypatch.setattr(_ui, "prompt_approve_plan", _boom)

    # No exception → the approval gate was never hit, and the files got built.
    _loop.run_turn_autonomous(console, session, "write a greeting helper and a CLI")
    assert (tmp_path / "greet.py").is_file()
    assert (tmp_path / "cli.py").is_file()


def test_execute_nudges_past_a_prose_only_step(console, session, tmp_path) -> None:
    """A single prose-only step (no tool call, no <done>) shouldn't end the task
    — the loop nudges the model to keep going, and it then finishes the work."""
    stub = StubProvider(
        responses=[
            "Let me think about how to approach this…",          # prose only
            _call("write_file", path="made.txt", content="ok\n"),  # then it acts
            "<done>created made.txt</done>",
        ],
        auto_respond=False,
    )
    result = _agent_exec.execute(
        console, session, "create made.txt", Context(),
        make_runtime=lambda p, m: LiteRuntime(stub),
    )
    assert (tmp_path / "made.txt").is_file()
    assert result.stopped_reason == "done"


def test_execute_ask_user_prompts_and_feeds_back(monkeypatch, console, session, tmp_path) -> None:
    """The agent can ask the user a multiple-choice question mid-task; the chosen
    answer is fed back and the loop continues to completion."""
    captured: dict = {}

    def fake_ask(c, spec, *, input_fn=None):
        captured["spec"] = spec
        return "Q: Which framework?\nA: React"

    monkeypatch.setattr(_ui, "ask_user_questions", fake_ask)
    stub = StubProvider(
        responses=[
            _call("ask_user", questions=[{"question": "Which framework?", "options": ["React", "Vue"]}]),
            _call("write_file", path="app.jsx", content="// React app\n"),
            "<done>scaffolded a React app</done>",
        ],
        auto_respond=False,
    )
    result = _agent_exec.execute(
        console, session, "scaffold a frontend", Context(),
        make_runtime=lambda p, m: LiteRuntime(stub),
    )
    assert captured["spec"]["questions"][0]["question"] == "Which framework?"
    assert (tmp_path / "app.jsx").is_file()  # it acted on the answer
    assert result.stopped_reason == "done"


def test_ask_user_questions_select_and_other(console) -> None:
    """ask_user UI: a number selects an option; the 'Other' number takes typed text."""
    spec = {"questions": [
        {"question": "Pick a color", "header": "Color", "options": ["Red", "Green", "Blue"]},
        {"question": "Pick a size", "options": ["S", "M"]},
    ]}
    # Q1: "2" → Green. Q2 has 2 options so "3" is Other → next input "Large".
    inputs = iter(["2", "3", "Large"])
    out = _ui.ask_user_questions(console, spec, input_fn=lambda prompt: next(inputs))
    assert "A: Green" in out
    assert "A: Large" in out


def test_ask_user_questions_non_interactive_does_not_block(console) -> None:
    """With no TTY and no injected input_fn, ask_user never blocks — it returns a
    note telling the model to proceed."""
    out = _ui.ask_user_questions(console, {"question": "x?", "options": ["a", "b"]})
    assert "no interactive user" in out.lower()


def test_executor_carries_conversation_memory(session) -> None:
    """Prior turns + running background processes show up in the executor's
    system prompt, so follow-up questions are answered from memory."""
    session.history.append(
        TaskTurn(task="code a website", summary="Built a 4-page static site",
                 files_touched=["index.html", "styles.css"])
    )
    mem = _agent_exec._conversation_memory(session)
    assert "code a website" in mem
    assert "Built a 4-page static site" in mem
    assert "index.html" in mem
    # And it's actually woven into the system prompt.
    system = _agent_exec._system_prompt(Context(), memory=mem)
    assert "CONVERSATION SO FAR" in system


def test_infer_url_from_background_command() -> None:
    f = _agent_exec._infer_url
    assert f("python3 -m http.server 8000") == "http://localhost:8000"
    assert f("flask run --port 5001") == "http://localhost:5001"
    assert f("python manage.py runserver 0.0.0.0:8001") == "http://localhost:8001"
    assert f("next dev") == "http://localhost:3000"   # framework default
    assert f("echo hello") is None


def test_conversation_memory_includes_actions_and_server_url(session, monkeypatch) -> None:
    """Memory recalls the concrete actions of the last turn AND a reachable URL
    for a running server, so 'what did you just do?' / 'how do I reach it?' work."""
    t = TaskTurn(task="serve the site")
    t.summary = "served it"
    t.actions = ["Created index.html", "Started Simple HTTP Server"]
    session.history.append(t)

    class _BG:
        id = "ab12"; name = "Simple HTTP Server"; cmd = "python3 -m http.server 8000"
        status = "running"; exit_code = None; is_running = True

    monkeypatch.setattr(
        "essarion_build.agent._background.current_manager",
        lambda: type("M", (), {"poll_all": staticmethod(lambda: [_BG()])})(),
    )
    mem = _agent_exec._conversation_memory(session)
    assert "Created index.html" in mem and "Started Simple HTTP Server" in mem
    assert "http://localhost:8000" in mem
    assert "still running" in mem


def test_execute_blocks_risky_shell_when_noninteractive(monkeypatch, console, session, tmp_path) -> None:
    """A risky command (rm -rf) is 'ask' → with no interactive user it's denied,
    so it never runs. The agent gets a 'blocked' result and moves on."""
    monkeypatch.setattr("essarion_build.agent._tools._AUTO_APPROVE", False)
    (tmp_path / "keep.txt").write_text("important\n")
    stub = StubProvider(responses=[
        _call("run_shell", cmd="rm -rf keep.txt"),
        "<done>tried to clean up</done>",
    ], auto_respond=False)
    _agent_exec.execute(
        console, session, "clean up", Context(),
        make_runtime=lambda p, m: LiteRuntime(stub),
    )
    assert (tmp_path / "keep.txt").is_file()  # NOT deleted — the command was blocked
    assert "Blocked" in console.file.getvalue()


def test_execute_tracks_and_renders_todos(console, session) -> None:
    """update_todos drives the visible checklist and is stored on the result."""
    stub = StubProvider(responses=[
        _call("update_todos", todos=[
            {"text": "Scaffold the app", "status": "doing"},
            {"text": "Add tests", "status": "todo"},
        ]),
        "<done>set up the plan</done>",
    ], auto_respond=False)
    result = _agent_exec.execute(
        console, session, "build", Context(),
        make_runtime=lambda p, m: LiteRuntime(stub),
    )
    assert result.todos and result.todos[0]["text"] == "Scaffold the app"
    assert "Scaffold the app" in console.file.getvalue()


def test_render_todos_only_renders_changes(console) -> None:
    """First call shows the full plan; an unchanged call is silent; an advance
    shows only the changed lines (no full re-print)."""
    plan = [{"text": "A", "status": "doing"}, {"text": "B", "status": "todo"}, {"text": "C", "status": "todo"}]
    _ui.render_todos(console, plan, None)
    first = console.file.getvalue()
    assert "todo" in first and "A" in first and "B" in first and "C" in first

    before = console.file.getvalue()  # re-sending the same list → nothing
    _ui.render_todos(console, plan, plan)
    assert console.file.getvalue() == before

    nxt = [{"text": "A", "status": "done"}, {"text": "B", "status": "doing"}, {"text": "C", "status": "todo"}]
    _ui.render_todos(console, nxt, plan)
    delta = console.file.getvalue()[len(before):]
    assert "A" in delta and "B" in delta  # the two items that advanced
    assert "C" not in delta               # unchanged item not reprinted
    assert "todo\n" not in delta          # and no full-list header on a delta


def test_render_action_shows_diffstat_not_code(console) -> None:
    _ui.render_action(console, verb="Edited", target="app.py", ok=True, diffstat=(12, 3))
    out = console.file.getvalue()
    assert "Edited" in out and "app.py" in out
    assert "+12" in out and "−3" in out   # counts, not the code body


def test_diff_stat_counts() -> None:
    from essarion_build.agent._agent_exec import _diff_stat

    assert _diff_stat({"old": "a\nb\nc", "new": "a\nX\nc\nd"}) == (2, 1)
    assert _diff_stat({"old": "", "new": ""}) == (0, 0)


def test_execute_marks_nonzero_shell_exit_as_failed(monkeypatch, console, session) -> None:
    """A command that runs but exits nonzero shows ✗, not a misleading ✓."""
    monkeypatch.setattr("essarion_build.agent._tools._AUTO_APPROVE", False)
    stub = StubProvider(responses=[
        _call("run_shell", cmd="exit 7"),
        "<done>ran it</done>",
    ], auto_respond=False)
    _agent_exec.execute(
        console, session, "run a failing command", Context(),
        make_runtime=lambda p, m: LiteRuntime(stub),
    )
    out = console.file.getvalue()
    assert "✗" in out and "Ran" in out


def test_render_action_redacts_secrets(console) -> None:
    """Keys/tokens are stripped from rendered tool output."""
    key = "sk-or-v1-abcdef0123456789abcdef0123"
    _ui.render_action(console, verb="Ran", target=f"echo {key}", ok=True, output=f"token={key}")
    out = console.file.getvalue()
    assert key not in out
    assert "REDACTED" in out


def test_mark_last_cacheable_adds_breakpoint() -> None:
    """The Anthropic provider marks the final message for prompt caching."""
    from essarion_build._providers import _mark_last_cacheable

    msgs = [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
    _mark_last_cacheable(msgs)
    last = msgs[-1]["content"]
    assert isinstance(last, list) and last[-1]["cache_control"] == {"type": "ephemeral"}
    assert msgs[0]["content"] == "a"  # earlier messages untouched


def test_execute_gives_up_after_repeated_no_action(console, session) -> None:
    """If the model never acts, the loop nudges a bounded number of times and
    then stops with no_action — it does not spin forever."""
    stub = StubProvider(responses=["thinking, no actions…"] * 10, auto_respond=False)
    result = _agent_exec.execute(
        console, session, "stall", Context(),
        make_runtime=lambda p, m: LiteRuntime(stub), max_steps=20,
    )
    assert result.stopped_reason == "no_action"
    # 2 nudges + the final give-up step = 3 model calls, well under the cap.
    assert result.steps == 3
