"""Zero-dependency `.env` loading.

Used in two places:
- at **startup** (so a key sitting in `.env` just works — no `export`, no
  restart), loaded non-overriding so a shell-exported var still wins;
- by **`/reload`** (override=True), to pick up a key you just added live.

Deliberately tiny: `KEY=VALUE` per line, `#` comments, an optional `export`
prefix, and surrounding single/double quotes stripped. Not a full dotenv
implementation — no variable expansion — by design.
"""

from __future__ import annotations

import os
from pathlib import Path


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse `.env` text into a {KEY: VALUE} dict (no side effects)."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, val = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if key:
            out[key] = val
    return out


def load_dotenv_files(paths, *, override: bool = False) -> list[str]:
    """Load each `.env` path into `os.environ`. Returns the key NAMES set (deduped,
    never the values). Non-overriding by default — a var already in the
    environment (e.g. shell-exported) wins, matching dotenv convention."""
    loaded: list[str] = []
    seen: set[str] = set()
    for p in paths:
        path = Path(p)
        if not path.is_file():
            continue
        try:
            kv = parse_dotenv(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        for key, val in kv.items():
            if not override and os.environ.get(key):
                continue
            os.environ[key] = val
            if key not in seen:
                seen.add(key)
                loaded.append(key)
    return loaded


def default_env_paths(cwd, project_root=None) -> list[Path]:
    """The `.env` files we look for: the project root's, then the cwd's (cwd
    last so it can override the project default when `override=True`)."""
    paths: list[Path] = []
    if project_root is not None and Path(project_root) != Path(cwd):
        paths.append(Path(project_root) / ".env")
    paths.append(Path(cwd) / ".env")
    return paths


def upsert_dotenv(path, key: str, value: str) -> None:
    """Set `key=value` in the `.env` at `path`, updating an existing line in
    place or appending a new one. Creates the file (and parents) if missing."""
    path = Path(path)
    line = f"{key}={value}"
    lines: list[str] = []
    found = False
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            target = stripped[len("export "):].lstrip() if stripped.startswith("export ") else stripped
            if target.split("=", 1)[0].strip() == key:
                lines.append(line)
                found = True
            else:
                lines.append(raw)
    if not found:
        lines.append(line)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


__all__ = ["parse_dotenv", "load_dotenv_files", "default_env_paths", "upsert_dotenv"]
