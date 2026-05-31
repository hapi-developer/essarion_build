"""Proof that the autonomous agent can do what Claude Code does: write code,
RUN it (tests), observe the real output, fix the bug, re-run, and finish.

The provider here is *reactive*, not a fixed script: it branches on the actual
shell output fed back into the loop. So the test fails unless the write→run→
observe→fix→re-run feedback loop genuinely works against real subprocesses."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest
from rich.console import Console

from essarion_build import Context, ProviderResponse, Usage
from essarion_build._runtime import LiteRuntime
from essarion_build.agent import _agent_exec
from essarion_build.agent._session import Session, TaskTurn, new_session_id
from essarion_build.agent._theme import ESSARION_THEME
from essarion_build.agent._tools import bind_tools, register_all


def _call(name: str, **args: object) -> str:
    return f'<tool_call name="{name}">{json.dumps(args)}</tool_call>'


_TEST_SRC = (
    "import unittest\n"
    "from calc import add\n\n"
    "class TestAdd(unittest.TestCase):\n"
    "    def test_add(self):\n"
    "        self.assertEqual(add(2, 3), 5)\n\n"
    'if __name__ == "__main__":\n'
    "    unittest.main()\n"
)
# Run the tests with this interpreter (resolves regardless of PATH). `-B`
# disables .pyc caching so the re-run after the fix recompiles calc.py instead
# of serving stale bytecode — the two runs are <1s apart and Python's pyc mtime
# check has 1-second resolution. (A real agent edits seconds apart, so this only
# bites a fast deterministic test, not real use.)
_RUN_TESTS = _call("run_shell", cmd=f"{sys.executable} -B -m unittest test_calc -v")


class _ReactiveProvider:
    """Drives a real build-test-fix loop, branching on live tool output.

    State worth asserting on afterwards: `saw_failure` (did it actually observe
    the failing run?) and `runs` (how many times it executed the tests)."""

    def __init__(self) -> None:
        self.step = 0
        self.saw_failure = False
        self.runs = 0

    def _resp(self, text: str) -> ProviderResponse:
        return ProviderResponse(
            text=text, usage=Usage(prompt_tokens=20, completion_tokens=10, total_tokens=30)
        )

    def complete(self, *, system, messages, max_tokens) -> ProviderResponse:
        last = messages[-1]["content"] if messages else ""

        # React to a FAILING test run: fix the bug in calc.py.
        if "FAILED" in last or "AssertionError" in last:
            self.saw_failure = True
            return self._resp(
                _call("apply_diff", path="calc.py", old="return a - b", new="return a + b")
            )
        # React to a PASSING test run: we're done.
        if "Ran 1 test" in last and "OK" in last:
            return self._resp("<done>fixed add(); unittest passes</done>")

        # Otherwise advance the build: write buggy code, write the test, run it.
        self.step += 1
        if self.step == 1:
            return self._resp(
                _call("write_file", path="calc.py", content="def add(a, b):\n    return a - b\n")
            )
        if self.step == 2:
            return self._resp(_call("write_file", path="test_calc.py", content=_TEST_SRC))
        # step 3, and again after the fix: run the tests.
        self.runs += 1
        return self._resp(_RUN_TESTS)


@pytest.fixture
def console() -> Console:
    return Console(theme=ESSARION_THEME, file=io.StringIO(), force_terminal=False, width=120)


@pytest.fixture
def session(tmp_path: Path) -> Session:
    bind_tools(tmp_path)
    register_all()
    return Session(
        id=new_session_id(), cwd=str(tmp_path), provider="stub", model="m",
        budget_usd=1.00, effort="quick", autonomous=True,
    )


def test_agent_writes_code_runs_tests_fixes_and_reruns(console, session, tmp_path) -> None:
    provider = _ReactiveProvider()
    turn = TaskTurn(task="build + test add()")
    result = _agent_exec.execute(
        console, session, "write add() with a unittest, run it, make it pass", Context(),
        make_runtime=lambda p, m: LiteRuntime(provider), turn=turn, max_steps=20,
    )

    # The code and the test both landed on disk, and the bug was actually fixed.
    assert (tmp_path / "calc.py").is_file()
    assert (tmp_path / "test_calc.py").is_file()
    assert "return a + b" in (tmp_path / "calc.py").read_text(), "bug was not fixed on disk"

    # The fix was DRIVEN by observing the real failing run — not pre-scripted.
    assert provider.saw_failure, "agent never observed the failing test output"
    assert provider.runs >= 2, "agent did not re-run the tests after fixing"
    assert result.stopped_reason == "done"

    # Both a failing and a passing test run were really executed and rendered.
    out = console.file.getvalue()
    assert "run_shell" in out
    assert "FAILED" in out, "no real failing run was observed"
    assert "OK" in out, "no real passing run was observed"


def test_agent_can_run_arbitrary_code_and_capture_output(console, session, tmp_path) -> None:
    """The simplest form of the capability: write a script, run it, see stdout."""
    provider_responses = [
        _call("write_file", path="hello.py", content="print('hello from essarion')\n"),
        _call("run_shell", cmd=f"{sys.executable} hello.py"),
        "<done>ran hello.py</done>",
    ]

    class _Scripted:
        i = 0
        def complete(self, *, system, messages, max_tokens):
            text = provider_responses[self.i]
            self.i += 1
            return ProviderResponse(text=text, usage=Usage(total_tokens=10))

    result = _agent_exec.execute(
        console, session, "write and run a hello script", Context(),
        make_runtime=lambda p, m: LiteRuntime(_Scripted()),
    )
    assert (tmp_path / "hello.py").is_file()
    assert result.stopped_reason == "done"
    # The script's stdout was captured and surfaced.
    assert "hello from essarion" in console.file.getvalue()
