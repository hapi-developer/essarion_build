"""Post-generation validators: cheap, deterministic checks on generated code.

These do NOT call a model. They run pure Python validators (and a few
syntactic checks via the stdlib) on the `code` field of a `Generation`.

Use them as a safety net after `generate()`:

    g = generate("write a Python function …", context=ctx)
    issues = validate(g.code, kind="python")
    if issues:
        # decide whether to repair, regenerate, or just surface to the user
        ...

Each validator returns a list of `Issue` records (empty list = clean).
"""

from __future__ import annotations

import ast
import json
import re
import tokenize
from io import StringIO
from typing import Callable, Iterable, Literal

from pydantic import BaseModel


Severity = Literal["info", "warning", "error"]


class Issue(BaseModel):
    """One finding from a validator. `line` is 1-indexed; 0 for unspecified."""

    kind: str
    message: str
    line: int = 0
    severity: Severity = "warning"


def validate_python(code: str) -> list[Issue]:
    """Syntax + a few cheap correctness checks for Python code.

    Checks:
    - parses with `ast`
    - flags bare `except:` clauses
    - flags `eval(` / `exec(` (security)
    - flags TODO/FIXME comments (info)
    - flags mutable default args (e.g. `def f(x=[]):`)
    """
    issues: list[Issue] = []

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        issues.append(
            Issue(
                kind="syntax",
                message=f"SyntaxError: {e.msg}",
                line=e.lineno or 0,
                severity="error",
            )
        )
        return issues  # rest of the checks would all blow up on broken AST

    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            issues.append(
                Issue(
                    kind="bare_except",
                    message="bare except: clause hides bugs; catch a specific exception",
                    line=node.lineno,
                    severity="warning",
                )
            )
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"eval", "exec"}:
                issues.append(
                    Issue(
                        kind="dangerous_call",
                        message=f"{node.func.id}() on potentially untrusted input is dangerous",
                        line=node.lineno,
                        severity="error",
                    )
                )
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for default in node.args.defaults + node.args.kw_defaults:
                if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                    issues.append(
                        Issue(
                            kind="mutable_default",
                            message=(
                                f"mutable default argument in {node.name}() — "
                                "share across calls; use None and check inside"
                            ),
                            line=node.lineno,
                            severity="warning",
                        )
                    )
                    break

    # Token-level TODO/FIXME scan (comments).
    try:
        for tok in tokenize.generate_tokens(StringIO(code).readline):
            if tok.type == tokenize.COMMENT:
                m = re.search(r"\b(TODO|FIXME|XXX|HACK)\b", tok.string)
                if m:
                    issues.append(
                        Issue(
                            kind="open_marker",
                            message=f"{m.group(1)} marker in generated code",
                            line=tok.start[0],
                            severity="info",
                        )
                    )
    except tokenize.TokenError:
        # The AST already parsed; if tokenizing fails the code is still valid
        # to run but unusual encoding — skip the comment scan rather than
        # surface a confusing error.
        pass

    return issues


def validate_json(code: str) -> list[Issue]:
    """Strict JSON validity (RFC 8259). No trailing commas, no comments."""
    try:
        json.loads(code)
    except json.JSONDecodeError as e:
        return [
            Issue(
                kind="syntax",
                message=f"invalid JSON: {e.msg}",
                line=e.lineno,
                severity="error",
            )
        ]
    return []


_DIFF_HEADER = re.compile(r"^(diff --git |--- |\+\+\+ |@@ )", re.MULTILINE)


def validate_unified_diff(code: str) -> list[Issue]:
    """Sanity-check that a string looks like a unified diff.

    Not a structural parser — just looks for the canonical headers. Catches
    the most common failure mode: the model returned a code snippet when a
    diff was requested.
    """
    if not _DIFF_HEADER.search(code):
        return [
            Issue(
                kind="not_a_diff",
                message=(
                    "output does not look like a unified diff "
                    "(no `diff --git` / `--- ` / `+++ ` / `@@ ` headers)"
                ),
                severity="error",
            )
        ]
    return []


_VALIDATORS: dict[str, Callable[[str], list[Issue]]] = {
    "python": validate_python,
    "json": validate_json,
    "diff": validate_unified_diff,
}


def validate(code: str, *, kind: str) -> list[Issue]:
    """Dispatch helper: `validate(code, kind="python")`.

    Unknown `kind` returns no issues — the SDK doesn't try to be a universal
    linter. Use one of: 'python', 'json', 'diff'.
    """
    fn = _VALIDATORS.get(kind)
    if fn is None:
        return []
    return fn(code)


def register_validator(kind: str, validator: Callable[[str], list[Issue]]) -> None:
    """Register a custom validator for a new `kind`. Lets teams plug in their
    own language checks."""
    _VALIDATORS[kind] = validator


def list_validators() -> list[str]:
    return sorted(_VALIDATORS.keys())


__all__ = [
    "Issue",
    "validate",
    "validate_python",
    "validate_json",
    "validate_unified_diff",
    "register_validator",
    "list_validators",
]
