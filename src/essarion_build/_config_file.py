"""Optional config-file loader: `.essarion.toml` in the cwd or user config.

Lets teams keep provider / model / max-tokens / skills selection in a
TOML file checked into the repo instead of sprinkling `configure()` calls
through every script.

Lookup order (first hit wins):
1. Explicit path passed to `load_config_file(path)`
2. `./essarion.toml` (project-scoped)
3. `~/.config/essarion/config.toml` (user-scoped)

Example file:

    [defaults]
    provider = "anthropic"
    model = "claude-sonnet-4-6"
    max_tokens = 3000

    [defaults.skills]
    # An optional starter skill set the SDK loads when load_config_file
    # is called without explicit skills.
    enabled = ["secure_coding", "scope_discipline", "testing"]
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ._config import configure


def _toml_load(text: str) -> dict[str, Any]:
    if sys.version_info >= (3, 11):
        import tomllib

        return tomllib.loads(text)
    import tomli  # pragma: no cover - only needed on <3.11

    return tomli.loads(text)


def _candidate_paths(explicit: str | Path | None) -> list[Path]:
    out: list[Path] = []
    if explicit is not None:
        out.append(Path(explicit))
    else:
        out.append(Path("essarion.toml"))
        out.append(Path.home() / ".config" / "essarion" / "config.toml")
    return out


def load_config_file(
    path: str | Path | None = None,
) -> tuple[dict[str, Any], Path | None]:
    """Read a TOML config and apply its `[defaults]` section via `configure()`.

    Returns `(parsed_dict, path_actually_used)`. `path_actually_used` is
    `None` when no candidate file existed; the function is a no-op in
    that case (no error — config files are optional).
    """
    for p in _candidate_paths(path):
        if p.is_file():
            data = _toml_load(p.read_text(encoding="utf-8"))
            defaults = data.get("defaults") or {}
            kwargs: dict[str, Any] = {}
            for key in ("provider", "runtime", "model", "triage_model", "api_key", "max_tokens", "effort"):
                if key in defaults:
                    kwargs[key] = defaults[key]
            if kwargs:
                configure(**kwargs)
            return data, p
    return {}, None


def starter_skills(parsed: dict[str, Any]) -> list[str]:
    """Pull the `[defaults.skills].enabled` list out of a parsed config dict.

    Returns an empty list if the section is missing — callers can `if not
    starter_skills(...): default to with_all_skills()`.
    """
    return list(
        parsed.get("defaults", {}).get("skills", {}).get("enabled", []) or []
    )


__all__ = ["load_config_file", "starter_skills"]
