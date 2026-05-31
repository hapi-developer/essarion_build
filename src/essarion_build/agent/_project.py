"""Project folder semantics for the agent.

When the user runs `essarion` from inside a project, the agent should:

- detect the project root (look for .essarion/, then .git/, then common
  project files like pyproject.toml / package.json / Cargo.toml / go.mod)
- store sessions in `<project_root>/.essarion/sessions/` instead of the
  global `~/.essarion/sessions/`
- pick up per-project defaults from `<project_root>/.essarion/config.toml`
- set the sandbox CWD to the project root unless overridden

`essarion init` creates the `.essarion/` skeleton for a new project.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel


# Files whose presence in a directory means "this is the project root".
# Ordered by how strongly they signal a root — `.essarion/` wins over
# `.git/`, which wins over a language-specific config file.
_ROOT_MARKERS = [
    ".essarion",
    ".git",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Gemfile",
]


class Project(BaseModel):
    """Resolved project metadata. `root` is the project's top-level directory."""

    root: Path
    detected_by: str = ""  # which marker we found ("" = fell back to cwd)

    @property
    def has_essarion_dir(self) -> bool:
        return (self.root / ".essarion").is_dir()

    @property
    def essarion_dir(self) -> Path:
        return self.root / ".essarion"

    @property
    def sessions_dir(self) -> Path:
        """Where to persist sessions. Per-project when `.essarion/` exists,
        else the global `~/.essarion/sessions/` fallback."""
        if self.has_essarion_dir:
            d = self.essarion_dir / "sessions"
            d.mkdir(parents=True, exist_ok=True)
            return d
        d = Path.home() / ".essarion" / "sessions"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def config_path(self) -> Path | None:
        """Per-project config path. None if no `.essarion/config.toml`."""
        p = self.essarion_dir / "config.toml"
        return p if p.is_file() else None


def find_project_root(start: str | Path | None = None) -> Project:
    """Walk up from `start` looking for a project-root marker.

    `start` defaults to the current working directory. Returns a `Project`
    whose `root` is the first directory that contains a marker, or `start`
    itself if no marker is found within `start` or any ancestor.
    """
    here = Path(start or Path.cwd()).resolve()
    cur: Path | None = here
    while cur is not None:
        for marker in _ROOT_MARKERS:
            candidate = cur / marker
            if candidate.exists():
                return Project(root=cur, detected_by=marker)
        if cur.parent == cur:
            break
        cur = cur.parent
    return Project(root=here, detected_by="")


_STARTER_CONFIG = """# Per-project Essarion config. Loaded by `essarion` at REPL start.
# Per-call CLI flags > this file > ~/.config/essarion/config.toml > built-in defaults.

[defaults]
# provider = "openrouter"
# model = "openai/gpt-4o-mini"
# max_tokens = 4096

# [defaults.skills]
# enabled = ["secure_coding", "scope_discipline", "testing"]

[agent]
# budget = 1.00          # USD budget per session
# skills_mode = "auto"   # auto | all | none
# escalate_model = ""    # e.g. "anthropic/claude-sonnet-4-6"

# Lifecycle hooks — shell commands that run automatically on agent events.
# Events: pre_tool, post_tool, user_prompt, session_start, stop.
# A pre_tool hook that exits 2 BLOCKS the tool (stderr = the reason).
# {path}/{tool}/{command} are substituted (shell-quoted); the event payload
# is also on stdin and in ESSARION_HOOK_* env vars.
#
# [[hooks]]                       # auto-format Python after every write
# event = "post_tool"
# matcher = "write_file"
# command = "ruff format ."
# name = "format"
#
# [[hooks]]                       # refuse destructive shell commands
# event = "pre_tool"
# matcher = "run_shell"
# command = "case \"$ESSARION_HOOK_COMMAND\" in *'rm -rf'*) echo 'blocked: rm -rf' >&2; exit 2;; esac"
"""

_STARTER_GITIGNORE = """# sessions can contain prompts + generated code — usually don't check them in
sessions/
"""


def init_project(path: str | Path | None = None) -> Project:
    """Create `.essarion/` under `path` (default: cwd). Returns the Project.

    Idempotent: re-running `essarion init` won't clobber an existing config.
    """
    root = Path(path or Path.cwd()).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"init: {root} is not a directory")
    essarion = root / ".essarion"
    essarion.mkdir(exist_ok=True)
    (essarion / "sessions").mkdir(exist_ok=True)
    cfg = essarion / "config.toml"
    if not cfg.exists():
        cfg.write_text(_STARTER_CONFIG, encoding="utf-8")
    gi = essarion / ".gitignore"
    if not gi.exists():
        gi.write_text(_STARTER_GITIGNORE, encoding="utf-8")
    return Project(root=root, detected_by=".essarion")


def load_project_config(project: Project) -> dict[str, Any]:
    """Read `.essarion/config.toml` if present. Returns {} otherwise."""
    if project.config_path is None:
        return {}
    if sys.version_info >= (3, 11):
        import tomllib
    else:  # pragma: no cover - tested branch only on 3.11+
        import tomli as tomllib  # type: ignore[no-redef]
    try:
        return tomllib.loads(project.config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):  # type: ignore[attr-defined]
        return {}
