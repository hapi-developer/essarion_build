"""Lifecycle hooks — run shell commands automatically on agent events.

Mirrors Claude Code's hooks: user-configured shell commands that fire on
events to format code, validate/notify, or enforce rules. Opt-in via
`.essarion/config.toml`:

    [[hooks]]
    event   = "post_tool"      # pre_tool | post_tool | user_prompt | session_start | stop
    matcher = "write_file"     # tool name / fnmatch glob (tool events only; "*" = any)
    command = "ruff format ."  # shell command, run in the sandbox cwd
    name    = "format"         # optional label shown in the UI
    timeout = 30               # optional, seconds

    [[hooks]]
    event   = "pre_tool"
    matcher = "run_shell"
    command = "case \"$ESSARION_HOOK_COMMAND\" in *'rm -rf'*) exit 2;; esac"

Conventions (Claude Code parity):
- `pre_tool` hook exiting **2** blocks the tool; stderr/stdout is the reason
  (surfaced to the model so it can adapt). Other non-zero exits are
  non-blocking warnings.
- `user_prompt` hook exiting 2 cancels the turn.
- `post_tool` / `session_start` / `stop` are informational; their stdout is
  surfaced (post_tool output is folded into the tool result).

Each hook receives the event payload as JSON on stdin and as
`ESSARION_HOOK_*` env vars; `{path}` / `{tool}` in the command are
substituted (shell-quoted). No hooks configured == no behavior change.
"""

from __future__ import annotations

import fnmatch
import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


EVENTS = {"pre_tool", "post_tool", "user_prompt", "session_start", "stop"}


class Hook(BaseModel):
    event: str
    command: str
    matcher: str = "*"
    name: str = ""
    timeout: int = 30


class HookOutcome(BaseModel):
    blocked: bool = False
    reason: str = ""
    notes: list[str] = Field(default_factory=list)  # (label) text lines to surface


class HookBlocked(PermissionError):
    """Raised when a pre_tool hook (exit 2) denies a tool call."""


# Bound per session (alongside the tool sandbox) via bind_hooks().
_HOOKS: list[Hook] = []
_ROOT: Path = Path.cwd()


def bind_hooks(cwd: str | Path) -> list[Hook]:
    """Load `[[hooks]]` from `<project>/.essarion/config.toml`. Idempotent."""
    global _HOOKS, _ROOT
    _ROOT = Path(cwd).resolve()
    _HOOKS = _load_hooks(_ROOT)
    return _HOOKS


def list_hooks() -> list[Hook]:
    return list(_HOOKS)


def _load_hooks(cwd: Path) -> list[Hook]:
    from ._project import find_project_root, load_project_config

    try:
        cfg = load_project_config(find_project_root(cwd))
    except Exception:  # noqa: BLE001 - never let config break a session
        return []
    raw = cfg.get("hooks", [])
    if not isinstance(raw, list):
        return []
    out: list[Hook] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        event = str(item.get("event", "")).strip()
        command = str(item.get("command", "")).strip()
        if event not in EVENTS or not command:
            continue
        out.append(Hook(
            event=event,
            command=command,
            matcher=str(item.get("matcher", "*")) or "*",
            name=str(item.get("name", "")),
            timeout=int(item.get("timeout", 30) or 30),
        ))
    return out


def _matches(matcher: str, tool: str | None) -> bool:
    if tool is None:
        return True  # non-tool events ignore the matcher
    return matcher in ("*", tool) or fnmatch.fnmatch(tool, matcher)


def _substitute(command: str, payload: dict[str, Any]) -> str:
    out = command
    for key in ("path", "tool", "command"):
        if "{" + key + "}" in out:
            out = out.replace("{" + key + "}", shlex.quote(str(payload.get(key, ""))))
    return out


def _run_event(event: str, payload: dict[str, Any], tool: str | None = None):
    """Run every hook bound to `event` (and matching `tool`). Yields
    (hook, returncode, stdout, stderr)."""
    for hook in _HOOKS:
        if hook.event != event or not _matches(hook.matcher, tool):
            continue
        env = dict(os.environ)
        env["ESSARION_HOOK_EVENT"] = event
        env["ESSARION_HOOK_TOOL"] = tool or ""
        env["ESSARION_HOOK_PATH"] = str(payload.get("path", ""))
        env["ESSARION_HOOK_COMMAND"] = str(payload.get("command", ""))
        env["ESSARION_HOOK_PAYLOAD"] = json.dumps(payload, default=str)
        cmd = _substitute(hook.command, payload)
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=str(_ROOT), env=env,
                input=json.dumps(payload, default=str),
                capture_output=True, text=True, timeout=hook.timeout,
            )
            yield hook, proc.returncode, proc.stdout or "", proc.stderr or ""
        except subprocess.TimeoutExpired:
            yield hook, -1, "", f"hook timed out after {hook.timeout}s"
        except Exception as e:  # noqa: BLE001 - a broken hook must not crash a turn
            yield hook, -1, "", f"{type(e).__name__}: {e}"


def before_tool(tool: str, payload: dict[str, Any]) -> None:
    """Fire pre_tool hooks. Raises HookBlocked if one exits 2."""
    if not _HOOKS:
        return
    for hook, code, out, err in _run_event("pre_tool", payload, tool=tool):
        if code == 2:
            reason = (err or out or f"denied by hook {hook.name or hook.command!r}").strip()
            raise HookBlocked(f"{tool} blocked by hook: {reason}")


def after_tool(tool: str, payload: dict[str, Any], result: str) -> str:
    """Fire post_tool hooks; fold any output into the tool result string."""
    if not _HOOKS:
        return result
    notes: list[str] = []
    for hook, code, out, err in _run_event("post_tool", payload, tool=tool):
        label = hook.name or "hook"
        text = out.strip()
        if text:
            notes.append(f"[{label}] {text}")
        elif code not in (0, None):
            detail = err.strip()[:200]
            notes.append(f"[{label}] exited {code}" + (f": {detail}" if detail else ""))
    return result + "\n" + "\n".join(notes) if notes else result


def fire(event: str, payload: dict[str, Any], console=None) -> HookOutcome:
    """Fire a non-tool lifecycle event (session_start / user_prompt / stop).

    Surfaces each hook's output via `console` if given. For user_prompt, an
    exit-2 hook sets `blocked` so the caller can cancel the turn.
    """
    outcome = HookOutcome()
    if not _HOOKS:
        return outcome
    for hook, code, out, err in _run_event(event, payload):
        text = (out or err or "").strip()
        if text:
            outcome.notes.append(text)
            if console is not None:
                console.print(f"[meta][hook {hook.name or event}][/meta] {text[:300]}")
        if event == "user_prompt" and code == 2:
            outcome.blocked = True
            outcome.reason = (err or out or "blocked by hook").strip()
    return outcome


__all__ = [
    "Hook", "HookOutcome", "HookBlocked",
    "bind_hooks", "list_hooks", "before_tool", "after_tool", "fire", "EVENTS",
]
