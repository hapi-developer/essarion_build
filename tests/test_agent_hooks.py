"""Lifecycle hooks: shell commands that fire on agent tool/turn events.

Drives the real _hooks + _tools surface against a project whose
.essarion/config.toml declares hooks, using tiny portable shell commands
(touch / exit 2 / echo) so the tests are deterministic and need no model."""

from __future__ import annotations

from pathlib import Path

import pytest

from essarion_build.agent import _hooks, _tools


def _init_project(tmp_path: Path, config_body: str) -> None:
    ess = tmp_path / ".essarion"
    ess.mkdir()
    (ess / "config.toml").write_text(config_body, encoding="utf-8")


def test_no_hooks_is_a_no_op(tmp_path: Path) -> None:
    _tools.bind_tools(tmp_path)
    assert _hooks.list_hooks() == []
    # write/run still behave normally with no hooks configured.
    assert "wrote" in _tools.write_file("a.py", "x = 1\n")
    assert (tmp_path / "a.py").read_text() == "x = 1\n"


def test_post_tool_hook_runs_after_write(tmp_path: Path) -> None:
    # A post_tool hook on write_file drops a sentinel file and echoes a note.
    _init_project(tmp_path, "\n".join([
        "[[hooks]]",
        'event = "post_tool"',
        'matcher = "write_file"',
        'command = "touch formatted.marker && echo formatted"',
        'name = "fmt"',
    ]))
    _tools.bind_tools(tmp_path)
    assert len(_hooks.list_hooks()) == 1

    result = _tools.write_file("greet.py", "def greet():\n    return 'hi'\n")
    # The hook ran (sentinel exists) and its output folded into the result.
    assert (tmp_path / "formatted.marker").is_file()
    assert "[fmt] formatted" in result


def test_pre_tool_hook_exit_2_blocks_the_tool(tmp_path: Path) -> None:
    # A pre_tool hook that exits 2 must block run_shell before it executes.
    _init_project(tmp_path, "\n".join([
        "[[hooks]]",
        'event = "pre_tool"',
        'matcher = "run_shell"',
        "command = \"\"\"case \"$ESSARION_HOOK_COMMAND\" in *dangerous*) echo 'nope' >&2; exit 2;; esac\"\"\"",
    ]))
    _tools.bind_tools(tmp_path)

    # Non-matching command runs fine.
    assert "exit 0" in _tools.run_shell("echo safe").lower() or "safe" in _tools.run_shell("echo safe")

    # The dangerous command is blocked with the hook's reason.
    with pytest.raises(_hooks.HookBlocked) as exc:
        _tools.run_shell("do something dangerous")
    assert "nope" in str(exc.value)


def test_pre_tool_block_prevents_file_write(tmp_path: Path) -> None:
    _init_project(tmp_path, "\n".join([
        "[[hooks]]",
        'event = "pre_tool"',
        'matcher = "write_file"',
        'command = "exit 2"',
    ]))
    _tools.bind_tools(tmp_path)
    with pytest.raises(_hooks.HookBlocked):
        _tools.write_file("blocked.py", "should not exist")
    assert not (tmp_path / "blocked.py").exists()


def test_matcher_glob_scopes_the_hook(tmp_path: Path) -> None:
    # Hook only matches *.py writes; a .txt write is untouched.
    _init_project(tmp_path, "\n".join([
        "[[hooks]]",
        'event = "pre_tool"',
        'matcher = "write_file"',
        # block only when the path arg ends in .secret
        "command = \"\"\"case \"$ESSARION_HOOK_PATH\" in *.secret) exit 2;; esac\"\"\"",
    ]))
    _tools.bind_tools(tmp_path)
    assert "wrote" in _tools.write_file("ok.py", "1\n")
    with pytest.raises(_hooks.HookBlocked):
        _tools.write_file("creds.secret", "nope")


def test_user_prompt_and_stop_fire(tmp_path: Path) -> None:
    _init_project(tmp_path, "\n".join([
        "[[hooks]]",
        'event = "user_prompt"',
        'command = "echo saw-prompt"',
        "",
        "[[hooks]]",
        'event = "stop"',
        'command = "echo saw-stop"',
    ]))
    _tools.bind_tools(tmp_path)
    up = _hooks.fire("user_prompt", {"prompt": "do a thing"})
    assert not up.blocked
    assert any("saw-prompt" in n for n in up.notes)
    stop = _hooks.fire("stop", {"task": "t"})
    assert any("saw-stop" in n for n in stop.notes)


def test_user_prompt_exit_2_blocks_turn(tmp_path: Path) -> None:
    _init_project(tmp_path, "\n".join([
        "[[hooks]]",
        'event = "user_prompt"',
        'command = "exit 2"',
    ]))
    _tools.bind_tools(tmp_path)
    outcome = _hooks.fire("user_prompt", {"prompt": "blocked task"})
    assert outcome.blocked is True


def test_broken_hook_never_crashes_the_tool(tmp_path: Path) -> None:
    # A hook command that doesn't exist must not break the write.
    _init_project(tmp_path, "\n".join([
        "[[hooks]]",
        'event = "post_tool"',
        'matcher = "*"',
        'command = "this-command-does-not-exist-12345"',
        "timeout = 5",
    ]))
    _tools.bind_tools(tmp_path)
    result = _tools.write_file("a.py", "x = 1\n")
    assert (tmp_path / "a.py").is_file()
    assert "wrote" in result  # tool still succeeded
