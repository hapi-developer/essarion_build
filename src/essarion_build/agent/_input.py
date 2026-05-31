"""Claude-Code-style interactive input for the REPL.

The REPL calls :func:`read_prompt` once per turn; it returns the user's line
and then the loop runs it, so a fresh input line comes back after *every* turn
— no need to re-invoke `essarion` or pass `--task`.

When ``prompt_toolkit`` is installed and we're on an interactive TTY this gives
a persistent input line with:
  * command history that survives across turns and across sessions (↑/↓),
  * history-based autosuggestions (ghost text you accept with →),
  * slash-command tab-completion (only when the line starts with ``/``),
  * a dim placeholder and a hint toolbar.

For pipes / CI / non-TTY stdin, or if prompt_toolkit isn't available, it falls
back to a plain Rich prompt. Either way a whole line is read, so multi-word
input like "please code a website" is captured intact (no shell quoting, none
of the argparse "only the first word" problem of `--task`).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from ._session import Session

# Cached prompt_toolkit PromptSession (built lazily, reused every turn so the
# in-memory side of history is continuous). Set to a sentinel once we know
# prompt_toolkit is unusable so we stop retrying the import each turn.
_PT_SESSION = None
_PT_UNAVAILABLE = False


def _history_file(session: Optional[Session]) -> Path:
    """Where to persist input history.

    Project-local (``<cwd>/.essarion/history``) when we're inside an
    initialized project, else ``~/.essarion/history``.
    """
    base: Optional[Path] = None
    if session is not None:
        cand = Path(session.cwd) / ".essarion"
        if cand.is_dir():
            base = cand
    if base is None:
        base = Path.home() / ".essarion"
    base.mkdir(parents=True, exist_ok=True)
    return base / "history"


def _slash_commands() -> list[str]:
    try:
        from ._commands import COMMANDS

        return sorted(COMMANDS.keys())
    except Exception:  # noqa: BLE001 - completion is a nicety, never fatal
        return ["/help", "/quit"]


def _make_completer():
    """Complete slash commands, but only at the start of the line so plain
    prose is never interrupted by a completion menu."""
    from prompt_toolkit.completion import Completer, Completion

    commands = _slash_commands()

    class _SlashCompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            # Only the first token, and only if it's a slash command in progress.
            if not text.startswith("/") or " " in text:
                return
            for cmd in commands:
                if cmd.startswith(text):
                    yield Completion(cmd, start_position=-len(text))

    return _SlashCompleter()


def _build_session(session: Optional[Session], *, _input=None, _output=None):
    """Construct a prompt_toolkit PromptSession. The ``_input``/``_output``
    hooks let tests drive it headlessly via a pipe input."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.styles import Style

    style = Style.from_dict(
        {
            "prompt": "#00d4d4 bold",            # brand cyan — matches the banner ">"
            "bottom-toolbar": "#5da9a9 bg:#10242a",
            "placeholder": "#5f7f7f italic",
        }
    )
    return PromptSession(
        history=FileHistory(str(_history_file(session))),
        auto_suggest=AutoSuggestFromHistory(),
        completer=_make_completer(),
        complete_while_typing=True,
        style=style,
        input=_input,
        output=_output,
    )


def _session_for(session: Optional[Session]):
    global _PT_SESSION
    if _PT_SESSION is None:
        _PT_SESSION = _build_session(session)
    return _PT_SESSION


def read_prompt(console, session: Optional[Session] = None) -> str:
    """Read one line of user input for the REPL.

    Returns the line (stripped), or ``"/quit"`` on EOF (Ctrl-D). Ctrl-C cancels
    the current line and returns ``""`` so the caller simply re-prompts.
    """
    global _PT_UNAVAILABLE

    interactive = bool(getattr(sys.stdin, "isatty", lambda: False)()) and bool(
        getattr(sys.stdout, "isatty", lambda: False)()
    )
    if interactive and not _PT_UNAVAILABLE:
        try:
            from prompt_toolkit.formatted_text import HTML

            ps = _session_for(session)
            auto = bool(getattr(session, "autonomous", False)) if session else False
            mode = "<b>auto</b> (autonomous)" if auto else "plan-first"

            def _toolbar():
                return HTML(
                    f" {mode} · <b>/help</b> commands · <b>/auto</b> toggle · "
                    "<b>↑</b> history · <b>Ctrl-D</b> quit"
                )

            try:
                line = ps.prompt(
                    [("class:prompt", "> ")],
                    placeholder=HTML(
                        "<placeholder>Describe a task, or type /help …</placeholder>"
                    ),
                    bottom_toolbar=_toolbar,
                )
                return line.strip()
            except KeyboardInterrupt:
                return ""  # cancel current line; the REPL loop re-prompts
            except EOFError:
                return "/quit"
        except ImportError:
            _PT_UNAVAILABLE = True
        except Exception:  # noqa: BLE001 - any terminal quirk → safe fallback
            _PT_UNAVAILABLE = True

    # Fallback: plain Rich prompt (also the path for pipes / CI / non-TTY).
    from rich.prompt import Prompt

    try:
        return Prompt.ask("[you]>[/you]", console=console).strip()
    except (EOFError, KeyboardInterrupt):
        return "/quit"
