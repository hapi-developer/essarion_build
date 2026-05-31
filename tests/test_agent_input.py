"""The Claude-Code-style REPL input: prompt_toolkit when available (driven
headlessly here via a pipe input), plus the fallback and the entry-point /
multi-word-task fixes."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from essarion_build.agent import _input
from essarion_build.agent._theme import ESSARION_THEME

pt = pytest.importorskip("prompt_toolkit")
from prompt_toolkit.input import create_pipe_input  # noqa: E402
from prompt_toolkit.output import DummyOutput  # noqa: E402


def _drive(text: str, tmp_path: Path) -> str:
    """Build the real PromptSession and feed it `text` as if typed."""

    class _S:  # minimal stand-in for Session (only .cwd / .autonomous read)
        cwd = str(tmp_path)
        autonomous = False

    with create_pipe_input() as inp:
        inp.send_text(text)
        ps = _input._build_session(_S(), _input=inp, _output=DummyOutput())
        return ps.prompt().strip()


def test_multiword_line_is_captured_whole(tmp_path: Path) -> None:
    # The core fix: a sentence with spaces comes back intact (no "first word only").
    assert _drive("please code a website\r", tmp_path) == "please code a website"


def test_slash_command_line_passes_through(tmp_path: Path) -> None:
    assert _drive("/auto\r", tmp_path) == "/auto"


def test_history_file_is_project_local_when_initialized(tmp_path: Path) -> None:
    (tmp_path / ".essarion").mkdir()

    class _S:
        cwd = str(tmp_path)
        autonomous = False

    assert _input._history_file(_S()) == tmp_path / ".essarion" / "history"


def test_history_file_falls_back_to_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    # No .essarion in cwd → history lives under ~/.essarion.
    class _S:
        cwd = str(tmp_path / "nowhere")
        autonomous = False

    hf = _input._history_file(_S())
    assert hf == Path(str(tmp_path)) / ".essarion" / "history"


def test_slash_completer_only_fires_on_slash(tmp_path: Path) -> None:
    from prompt_toolkit.document import Document

    comp = _input._make_completer()
    # A leading slash offers command completions...
    got = [c.text for c in comp.get_completions(Document("/he"), None)]
    assert "/help" in got
    # ...but plain prose offers none (no menu mid-sentence).
    assert list(comp.get_completions(Document("please code"), None)) == []


def test_read_prompt_falls_back_when_not_a_tty(monkeypatch, tmp_path: Path) -> None:
    # In the test runner stdin isn't a TTY, so read_prompt uses the Rich path.
    console = Console(theme=ESSARION_THEME, file=io.StringIO())
    monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "  do a thing  ")
    assert _input.read_prompt(console) == "do a thing"
