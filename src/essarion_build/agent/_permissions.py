"""Permission policy for the autonomous executor.

An agent with real disk + shell access needs guardrails. This module decides,
per tool call, whether to **allow**, **ask** the user, or **deny** it:

- read tools (read_file/list_dir/grep/find/glob) → allow
- write/edit/delete + background → allow by default (undoable via the change log)
- run_shell / start_background → the command is screened against a built-in
  dangerous-command list (catastrophic → always deny; risky → ask, or deny when
  there's no interactive user to ask), plus any patterns from project config.

Configurable via `[permissions]` in `.essarion/config.toml`:

    [permissions]
    shell = "ask"            # allow | ask | deny  (also: write, delete, or per-tool)
    deny  = ["\\bterraform\\s+destroy\\b"]
    ask   = ["\\bgit\\s+push\\b"]
    allow = ["\\bnpm\\s+(run|test|install)\\b"]

`/yolo` (auto-approve) downgrades every "ask" to "allow" — but the catastrophic
list is always denied, even then.
"""

from __future__ import annotations

import re
from typing import Any

ALLOW = "allow"
ASK = "ask"
DENY = "deny"

# Catastrophic shell patterns — always denied, even with /yolo on.
_CATASTROPHIC = [
    r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+(?:/|~|/\*|\$HOME|--no-preserve-root)",
    r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+/\s*$",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",   # fork bomb
    r"\bmkfs\.",
    r"\bdd\b[^\n]*\bof=/dev/(?:sd|nvme|disk|hd)",
    r">\s*/dev/(?:sd|nvme|disk|hd)[a-z0-9]",
    r"\bchmod\s+-R\s+0?777\s+/(?:\s|$)",
    r"\b(?:shutdown|reboot|halt|poweroff)\b",
]
# Risky shell patterns — ask the user (or deny when non-interactive / allow on yolo).
_RISKY = [
    r"\bsudo\b",
    r"\bgit\s+push\b[^\n]*(?:--force\b|-f\b|--force-with-lease\b)",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-[a-z]*f",
    r"\bchmod\s+-R\s+0?777\b",
    r"\b(?:curl|wget)\b[^\n]*\|\s*(?:sudo\s+)?(?:sh|bash|zsh)\b",
    r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\b",            # any rm -rf (non-catastrophic path)
    r"\b(?:npm|pnpm|yarn)\s+publish\b",
    r"\bpip\s+install\b[^\n]*\b(?:https?://|git\+)",
]

_READ_TOOLS = {"read_file", "list_dir", "grep", "find_files", "glob"}
_SHELL_TOOLS = {"run_shell", "start_background"}


def _command_of(args: dict[str, Any]) -> str:
    return str(args.get("cmd", args.get("command", "")))


class PermissionPolicy:
    """Decides allow / ask / deny for a tool call. Built from project config."""

    def __init__(
        self,
        *,
        tool: dict[str, str] | None = None,
        allow_patterns: list[str] | None = None,
        deny_patterns: list[str] | None = None,
        ask_patterns: list[str] | None = None,
    ) -> None:
        self.tool = tool or {}
        self.allow_patterns = allow_patterns or []
        self.deny_patterns = deny_patterns or []
        self.ask_patterns = ask_patterns or []

    @classmethod
    def from_config(cls, cfg: dict | None) -> "PermissionPolicy":
        """Build from the `[permissions]` table of `.essarion/config.toml`."""
        cfg = cfg or {}
        tool: dict[str, str] = {}
        # Per-tool overrides, plus the friendly aliases shell/write/delete.
        for k, v in (cfg.get("tools") or {}).items():
            if v in (ALLOW, ASK, DENY):
                tool[str(k)] = v
        aliases = {
            "shell": ["run_shell", "start_background"],
            "write": ["write_file", "apply_diff"],
            "delete": ["delete_file"],
            "read": list(_READ_TOOLS),
        }
        for key, names in aliases.items():
            if cfg.get(key) in (ALLOW, ASK, DENY):
                for n in names:
                    tool[n] = cfg[key]
        return cls(
            tool=tool,
            allow_patterns=[str(p) for p in (cfg.get("allow") or [])],
            deny_patterns=[str(p) for p in (cfg.get("deny") or [])],
            ask_patterns=[str(p) for p in (cfg.get("ask") or [])],
        )

    def _base(self, name: str) -> str:
        if name in self.tool:
            return self.tool[name]
        if name in _READ_TOOLS:
            return ALLOW
        return ALLOW  # mutations are allowed by default (undoable); shell is screened

    def decide(self, name: str, args: dict[str, Any], *, yolo: bool = False) -> tuple[str, str]:
        """Return (decision, reason). decision ∈ {allow, ask, deny}."""
        if name in _SHELL_TOOLS:
            cmd = _command_of(args)
            for p in self.deny_patterns:
                if re.search(p, cmd):
                    return DENY, f"matches a denied command pattern ({p})"
            for p in _CATASTROPHIC:
                if re.search(p, cmd):
                    return DENY, "looks catastrophic (e.g. rm -rf /, mkfs, fork bomb) — refusing"
            for p in self.allow_patterns:
                if re.search(p, cmd):
                    return ALLOW, ""
            for p in self.ask_patterns + _RISKY:
                if re.search(p, cmd):
                    if yolo:
                        return ALLOW, ""
                    return ASK, "potentially destructive command"
        base = self._base(name)
        if base == ASK and yolo:
            return ALLOW, ""
        if base == ALLOW:
            return ALLOW, ""
        return base, f"{name} is set to '{base}' by your permission policy"
