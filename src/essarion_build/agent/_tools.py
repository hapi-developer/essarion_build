"""Built-in tools the agent can use.

These map onto the SDK's `essarion_build.tools.register_tool` surface
(so the `<tool_call name=…>…</tool_call>` mechanism can drive them) AND
are exposed for direct use by the agent's REPL when it needs to do file
I/O on the user's behalf.

Every tool here is **sandboxed** to the session's CWD (no path traversal
outside of it) and emits a structured record the UI can render and the
session can persist.

Side-effect tools (write_file, apply_diff, run_shell) are gated by
require_approval=True so the agent calls them with a confirmation hook;
read tools (read_file, list_dir, grep) run freely.
"""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .. import tools as sdk_tools
from . import _background, _changes, _diagnostics, _hooks


# Resolved per-session by the REPL via `bind_tools(cwd, ...)`. Keeping
# this module-level so the SDK's tool registry can call functions that
# already know their sandbox root without us threading state through
# every call site.
_SANDBOX_ROOT: Path = Path.cwd()
_AUTO_APPROVE: bool = False


def bind_tools(cwd: str | Path, *, auto_approve: bool = False) -> None:
    """Configure the sandbox root and the background-task manager.

    Called once per REPL session, plus whenever the user runs `/cd`.
    """
    global _SANDBOX_ROOT, _AUTO_APPROVE
    _SANDBOX_ROOT = Path(cwd).resolve()
    _AUTO_APPROVE = bool(auto_approve)
    _background.bind_manager(_SANDBOX_ROOT)
    _changes.bind_changelog(_SANDBOX_ROOT)
    _hooks.bind_hooks(_SANDBOX_ROOT)
    _diagnostics.configure(_SANDBOX_ROOT)


def _resolve(path: str) -> Path:
    """Resolve `path` against the sandbox root, refusing traversal."""
    p = (_SANDBOX_ROOT / path).resolve()
    if _SANDBOX_ROOT not in p.parents and p != _SANDBOX_ROOT:
        raise PermissionError(
            f"path {path!r} resolves outside the sandbox ({_SANDBOX_ROOT})"
        )
    return p


class ToolRun(BaseModel):
    """One tool invocation record — what the agent did, displayed in the UI."""

    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    ok: bool = True
    result: str = ""
    error: str = ""


# ---------- read-only tools ----------

def read_file(path: str, max_bytes: int = 64 * 1024, pattern: str = "") -> str:
    """Read a UTF-8 file under the sandbox root.

    A file larger than `max_bytes` is *windowed*, not head-truncated. With a
    `pattern` (a regex), the kept window centers on the matching lines and the
    function/class that encloses them — pass it to home in on a symbol in a big
    file cheaply. Without one, BOTH the head and the tail are preserved, because
    the end of a file (a `__main__` guard, a class's later methods) is often
    where the load-bearing logic lives and a blind prefix would miss it.
    """
    p = _resolve(path)
    if not p.is_file():
        raise FileNotFoundError(f"not a file: {path}")
    data = p.read_text(encoding="utf-8", errors="replace")
    if len(data) <= max_bytes:
        return data
    from .._windowing import smart_truncate

    windowed = smart_truncate(data, max_chars=max_bytes, pattern=pattern or None)
    return windowed + f"\n(file {path} is {len(data):,} bytes; shown windowed to ~{max_bytes:,})"


def list_dir(path: str = ".", max_entries: int = 200) -> str:
    """List entries directly under `path` (no recursion). Returns a plain text list."""
    p = _resolve(path)
    if not p.is_dir():
        raise NotADirectoryError(f"not a directory: {path}")
    entries: list[str] = []
    for child in sorted(p.iterdir()):
        if child.name.startswith(".") and child.name not in {".gitignore", ".env.example"}:
            continue
        kind = "d" if child.is_dir() else "f"
        try:
            size = child.stat().st_size if child.is_file() else 0
        except OSError:
            size = 0
        entries.append(f"{kind} {child.name}" + (f" ({size:,}B)" if kind == "f" else ""))
        if len(entries) >= max_entries:
            entries.append("... (truncated)")
            break
    return "\n".join(entries)


def grep(pattern: str, path: str = ".", max_hits: int = 50) -> str:
    """Search files under `path` for a regex `pattern`. Returns up to max_hits hits."""
    import re

    p = _resolve(path)
    try:
        rx = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"bad regex {pattern!r}: {e}")
    hits: list[str] = []
    for f in p.rglob("*"):
        if not f.is_file():
            continue
        if any(part in {".git", "__pycache__", "node_modules", ".venv"} for part in f.parts):
            continue
        try:
            for i, line in enumerate(
                f.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
            ):
                if rx.search(line):
                    rel = f.relative_to(_SANDBOX_ROOT).as_posix()
                    hits.append(f"{rel}:{i}: {line.strip()[:200]}")
                    if len(hits) >= max_hits:
                        return "\n".join(hits) + "\n... (truncated)"
        except OSError:
            continue
    return "\n".join(hits) if hits else "(no matches)"


# ---------- discovery tools ----------

# Directory names we never recurse into for find/glob.
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".mypy_cache", ".pytest_cache"}


def find_files(pattern: str, path: str = ".", max_hits: int = 200) -> str:
    """Find files under `path` whose name matches the fnmatch `pattern`.

    Pattern matches the file *name only*, not the relative path. Use
    `glob()` if you need path-shaped patterns like `src/**/*.py`.
    """
    root = _resolve(path)
    hits: list[str] = []
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        if any(part in _SKIP_DIRS for part in f.parts):
            continue
        if fnmatch.fnmatch(f.name, pattern):
            hits.append(f.relative_to(_SANDBOX_ROOT).as_posix())
            if len(hits) >= max_hits:
                hits.append("... (truncated)")
                break
    return "\n".join(hits) if hits else "(no matches)"


def glob(pattern: str, max_hits: int = 200) -> str:
    """Path-shaped glob from the sandbox root. Supports `**` recursion.

    Examples: `src/**/*.py`, `tests/test_*.py`, `*.md`.
    """
    hits: list[str] = []
    for p in _SANDBOX_ROOT.glob(pattern):
        # `Path.glob` keeps `..` segments literal, so a pattern like
        # `../../etc/*` escapes the sandbox and `relative_to` would NOT catch it.
        # Re-validate each hit against the root exactly like `_resolve` does for
        # every other file tool, so glob honours the same sandbox boundary.
        rp = p.resolve()
        if _SANDBOX_ROOT not in rp.parents and rp != _SANDBOX_ROOT:
            continue
        if not rp.is_file():
            continue
        if any(part in _SKIP_DIRS for part in rp.parts):
            continue
        hits.append(rp.relative_to(_SANDBOX_ROOT).as_posix())
        if len(hits) >= max_hits:
            hits.append("... (truncated)")
            break
    return "\n".join(hits) if hits else "(no matches)"


# ---------- code intelligence (read-only) ----------

def repo_map(focus: str = "", max_chars: int = 6000) -> str:
    """Ranked map of the codebase's most important symbols (classes/functions
    + signatures). Call this FIRST to orient before grepping or opening files.
    `focus` is a comma-separated list of paths to bias the ranking toward."""
    from . import _repomap

    idx = _repomap.build_index(_SANDBOX_ROOT)
    focus_set = {f.strip() for f in focus.split(",") if f.strip()} or None
    budget = max(500, min(int(max_chars), 20_000))
    return _repomap.render_map(idx, focus=focus_set, budget_chars=budget) or (
        "(no indexable source files found under the sandbox root)"
    )


def outline(path: str) -> str:
    """Table of contents for ONE file: its classes/functions/methods with
    signatures and line numbers — far cheaper than reading the whole file."""
    _resolve(path)  # enforce the sandbox boundary
    from . import _repomap

    return _repomap.outline_text(_SANDBOX_ROOT, path)


def find_symbol(name: str) -> str:
    """Go-to-definition + find-references in one call: where `name` is defined
    (with its signature) and every place it's used across the repo. Cheaper and
    more precise than grepping a bare name. Methods may be given as Class.method."""
    from . import _repomap

    return _repomap.find_symbol_text(_SANDBOX_ROOT, name)


def _strip_html(html_text: str) -> str:
    """Reduce an HTML document to readable text — no parser dependency."""
    import html as _html
    import re as _re

    html_text = _re.sub(r"(?is)<(script|style|head|nav|footer|svg)[^>]*>.*?</\1>", " ", html_text)
    html_text = _re.sub(r"(?s)<!--.*?-->", " ", html_text)
    html_text = _re.sub(r"(?i)<br\s*/?>", "\n", html_text)
    html_text = _re.sub(r"(?i)</(p|div|li|h[1-6]|tr|section|article)>", "\n", html_text)
    text = _html.unescape(_re.sub(r"(?s)<[^>]+>", " ", html_text))
    lines = (ln.strip() for ln in text.splitlines())
    return _re.sub(r"[ \t]{2,}", " ", "\n".join(ln for ln in lines if ln))


def web_fetch(url: str, max_chars: int = 8000) -> str:
    """Fetch an HTTP(S) URL and return its text (HTML reduced to readable text)
    — for reading docs, changelogs, RFCs, or an error page. Subject to the
    environment's network policy; returns an error string if egress is blocked."""
    import urllib.error
    import urllib.request

    from ._ssrf import UnsafeUrlError, assert_public_url, build_safe_opener

    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    # SSRF guard: the URL is model-chosen and can be steered by untrusted
    # content, so refuse internal targets (cloud metadata, localhost, RFC-1918)
    # up front and on every redirect hop.
    try:
        assert_public_url(url)
    except UnsafeUrlError as e:
        return f"(refused to fetch {url}: {e})"
    req = urllib.request.Request(url, headers={"User-Agent": "essarion-build-agent"})
    try:
        with build_safe_opener().open(req, timeout=20) as resp:  # noqa: S310 - explicit http(s)
            ctype = resp.headers.get("Content-Type", "")
            raw = resp.read(2_000_000)
    except UnsafeUrlError as e:
        return f"(refused to fetch {url}: redirected to a non-public address: {e})"
    except urllib.error.URLError as e:
        return f"(could not fetch {url}: {getattr(e, 'reason', e)})"
    except Exception as e:  # noqa: BLE001 - surface, don't crash
        return f"(could not fetch {url}: {type(e).__name__}: {e})"
    text = raw.decode("utf-8", errors="replace")
    if "html" in ctype.lower() or text.lstrip()[:1] == "<":
        text = _strip_html(text)
    text = text.strip()
    cap = max(500, min(int(max_chars), 20_000))
    if len(text) > cap:
        text = text[:cap].rstrip() + f"\n… (truncated; {len(raw):,} bytes fetched)"
    return text or "(empty response)"


# ---------- post-edit feedback (objective signals, never subjective critique) ----------

def _syntax_check(path: str, text: str) -> str:
    """Fast, dependency-free correctness gate on freshly written content.

    Returns a one-line diagnostic to append to the tool result, or "" when the
    content parses cleanly. Catching the syntax error the model just introduced
    in the SAME step is the cheapest, highest-value reliability gate there is
    (SWE-agent measured ~3 points lost without it). Only objective parse
    errors — no opinions about the code.
    """
    import sys

    suffix = Path(path).suffix.lower()
    try:
        if suffix in (".py", ".pyi"):
            compile(text, path, "exec")
        elif suffix == ".json":
            import json as _json

            _json.loads(text)
        elif suffix == ".toml" and sys.version_info >= (3, 11):
            import tomllib

            tomllib.loads(text)
    except SyntaxError as e:
        loc = f":{e.lineno}" if e.lineno else ""
        return f"⚠ Python syntax error in {path}{loc}: {e.msg} — fix before continuing."
    except ValueError as e:  # JSONDecodeError / TOMLDecodeError both subclass it
        return f"⚠ {suffix.lstrip('.').upper()} parse error in {path}: {e} — fix before continuing."
    return ""


def _impact_note(rel: str, before: str, after: str) -> str:
    """Blast-radius analysis: if an edit removed a symbol or changed its
    signature, warn which other files reference it so the model checks its
    callers instead of silently breaking them. Grounded in the symbol index;
    surfaced automatically at edit time. Python files only."""
    if Path(rel).suffix.lower() not in (".py", ".pyi"):
        return ""
    from . import _repomap

    before_defs = {d.name.split(".")[-1]: d.signature for d in _repomap._py_tags(before).defs}
    after_defs = {d.name.split(".")[-1]: d.signature for d in _repomap._py_tags(after).defs}
    risky: list[tuple[str, str]] = []  # (name, "removed" | "changed")
    for name, sig in before_defs.items():
        if name.startswith("_") or len(name) < 3:
            continue  # private / trivial — not worth a callers warning
        if name not in after_defs:
            risky.append((name, "removed"))
        elif after_defs[name] != sig:
            risky.append((name, "changed the signature of"))
    lines: list[str] = []
    for name, verb in risky[:3]:
        refs = _repomap.find_references(_SANDBOX_ROOT, name, exclude=rel, max_hits=8)
        if not refs:
            continue
        where = ", ".join(f"{r}:{ln}" for r, ln, _ in refs[:4])
        more = f" (+{len(refs) - 4} more)" if len(refs) > 4 else ""
        lines.append(f"↔ you {verb} `{name}`, referenced in {len(refs)} site(s): {where}{more} — check them.")
    return "\n".join(lines)


def _post_edit(path: str, after: str, before: str = "") -> str:
    """Combined edit-time feedback (syntax gate + blast radius), prefixed with a
    newline so it appends cleanly to a tool result. Best-effort: never raises."""
    notes: list[str] = []
    try:
        s = _syntax_check(path, after)
        if s:
            notes.append(s)
        elif _diagnostics.LINT_ON_EDIT:
            # Syntax is fine — ask an installed checker (ruff/pyflakes/ruby -c/…)
            # for real diagnostics. Auto-detected; silent when none is present.
            d = _diagnostics.diagnose(_SANDBOX_ROOT / path, root=_SANDBOX_ROOT)
            if d:
                notes.append(d)
        if before:
            imp = _impact_note(path, before, after)
            if imp:
                notes.append(imp)
    except Exception:  # noqa: BLE001 - feedback must never break an edit
        return ""
    return ("\n" + "\n".join(notes)) if notes else ""


# ---------- side-effect tools ----------

def write_file(path: str, content: str) -> str:
    """Write `content` to `path` (relative to sandbox). Creates parent dirs.

    Records the prior content in the session change log so the user can
    `/undo` to revert and `/diff` to inspect.
    """
    p = _resolve(path)
    _hooks.before_tool("write_file", {"path": path})
    before = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        _changes.current_changelog().record(
            path, after=content, sandbox_root=_SANDBOX_ROOT
        )
    except Exception:  # noqa: BLE001 - changelog must never block a write
        pass
    p.write_text(content, encoding="utf-8")
    msg = f"wrote {len(content):,} bytes to {path}" + _post_edit(path, content, before)
    return _hooks.after_tool("write_file", {"path": path}, msg)


def _fuzzy_replace(body: str, old: str, new: str) -> str | None:
    """Locate `old` in `body` tolerating leading/trailing-whitespace differences
    (the common LLM mismatch) and return the patched body — or None if there
    isn't exactly one fuzzy match. Tries trailing-whitespace tolerance first
    (preserves indentation), then full strip tolerance (re-indenting `new` to the
    matched block)."""
    body_lines = body.split("\n")
    old_lines = old.split("\n")
    if old_lines and old_lines[-1] == "":
        old_lines = old_lines[:-1]
    new_lines = new.split("\n")
    if new_lines and new_lines[-1] == "":
        new_lines = new_lines[:-1]
    n = len(old_lines)
    if n == 0:
        return None

    def _indent(s: str) -> str:
        return s[: len(s) - len(s.lstrip())]

    # 1) Trailing-whitespace tolerant — leading indentation must still match.
    target = [x.rstrip() for x in old_lines]
    hits = [i for i in range(len(body_lines) - n + 1)
            if [body_lines[i + j].rstrip() for j in range(n)] == target]
    if len(hits) == 1:
        i = hits[0]
        return "\n".join(body_lines[:i] + new_lines + body_lines[i + n:])

    # 2) Indentation tolerant — re-indent `new` to align with the matched block.
    target = [x.strip() for x in old_lines]
    hits = [i for i in range(len(body_lines) - n + 1)
            if [body_lines[i + j].strip() for j in range(n)] == target]
    if len(hits) == 1:
        i = hits[0]
        body_indent, old_indent = _indent(body_lines[i]), _indent(old_lines[0])
        pad = body_indent[len(old_indent):] if body_indent.startswith(old_indent) else ""
        reindented = [(pad + ln) if ln.strip() else ln for ln in new_lines]
        return "\n".join(body_lines[:i] + reindented + body_lines[i + n:])
    return None


def apply_diff(path: str, old: str, new: str) -> str:
    """Replace the *unique* occurrence of `old` with `new` in `path`.

    Refuses if `old` doesn't appear or appears more than once — this is
    the same safety the SDK's Edit tool surface uses. If `old` isn't found
    verbatim, falls back to a whitespace/indentation-tolerant match so a small
    formatting drift in the snippet doesn't waste a step. The full new file
    is recorded in the change log for `/undo`.
    """
    p = _resolve(path)
    if not p.is_file():
        raise FileNotFoundError(f"not a file: {path}")
    _hooks.before_tool("apply_diff", {"path": path})
    body = p.read_text(encoding="utf-8")
    count = body.count(old)
    if count == 1:
        new_body = body.replace(old, new)
        how = "applied 1-occurrence patch to"
    elif count > 1:
        raise ValueError(
            f"old text appears {count} times in {path}; tighten the snippet"
        )
    else:
        fuzzy = _fuzzy_replace(body, old, new)
        if fuzzy is None:
            raise ValueError(
                f"old text not found in {path}; read the file and copy the exact "
                "lines to replace (indentation is matched flexibly)"
            )
        new_body, how = fuzzy, "applied patch (whitespace-tolerant match) to"
    try:
        _changes.current_changelog().record(
            path, after=new_body, sandbox_root=_SANDBOX_ROOT
        )
    except Exception:  # noqa: BLE001
        pass
    p.write_text(new_body, encoding="utf-8")
    return _hooks.after_tool("apply_diff", {"path": path}, f"{how} {path}" + _post_edit(path, new_body, body))


def _replace_symbol_source(source: str, symbol: str, new_source: str) -> str:
    """Locate `symbol` (a def/class, or dotted `Class.method`) in `source` via
    `ast` and replace its full span — decorators included — with `new_source`,
    re-indented to the symbol's original column. Raises ValueError if not found.
    """
    import ast as _ast
    import textwrap

    tree = _ast.parse(source)

    def _find(body, names: list[str]):
        head, rest = names[0], names[1:]
        for n in body:
            if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)) and n.name == head:
                return n if not rest else _find(n.body, rest)
        return None

    target = _find(tree.body, symbol.split("."))
    if target is None:
        raise ValueError(
            f"symbol {symbol!r} not found (give a top-level def/class, or a "
            f"method as Class.method)"
        )
    start = min([target.lineno] + [d.lineno for d in getattr(target, "decorator_list", [])])
    end = getattr(target, "end_lineno", target.lineno) or target.lineno
    indent = " " * target.col_offset
    dedented = textwrap.dedent(new_source).strip("\n")
    new_lines = [(indent + ln) if ln.strip() else "" for ln in dedented.split("\n")]
    replacement = "\n".join(new_lines)

    lines = source.splitlines(keepends=True)
    head = "".join(lines[: start - 1])
    tail = "".join(lines[end:])
    if not replacement.endswith("\n"):
        replacement += "\n"
    return head + replacement + tail


def edit_symbol(path: str, symbol: str, new_source: str) -> str:
    """Replace a whole function or class BY NAME with `new_source` — an
    AST-anchored edit, more robust than apply_diff for rewriting a definition
    (no fuzzy text matching, no uniqueness ambiguity). `symbol` may be dotted
    for a method (e.g. "Parser.parse"). Python files only.

    Records the change for `/undo`; refuses to write if the result wouldn't
    parse, so a structural edit can never leave the file broken.
    """
    p = _resolve(path)
    if not p.is_file():
        raise FileNotFoundError(f"not a file: {path}")
    if p.suffix.lower() not in (".py", ".pyi"):
        raise ValueError("edit_symbol supports Python only; use apply_diff for other languages")
    _hooks.before_tool("edit_symbol", {"path": path})
    before = p.read_text(encoding="utf-8")
    new_body = _replace_symbol_source(before, symbol, new_source)
    try:
        compile(new_body, path, "exec")
    except SyntaxError as e:
        raise ValueError(
            f"that edit would not parse (line {e.lineno}: {e.msg}); the file was left unchanged"
        ) from None
    try:
        _changes.current_changelog().record(path, after=new_body, sandbox_root=_SANDBOX_ROOT)
    except Exception:  # noqa: BLE001
        pass
    p.write_text(new_body, encoding="utf-8")
    return _hooks.after_tool(
        "edit_symbol", {"path": path}, f"rewrote {symbol} in {path}" + _post_edit(path, new_body, before)
    )


def remember(fact: str) -> str:
    """Persist one durable project fact to project memory
    (`.essarion/memory.md`) — the agent reads it back at the start of every
    future turn. Self-accumulating memory: the agent saves what it learns
    (conventions, gotchas, where things live) without being asked.

    Facts are deduplicated; session noise and anything secret-shaped is
    refused. Manage by hand with `/remember` and `/forget`.
    """
    from ._memory import load_memory
    from ._ui import redact_secrets

    fact = " ".join((fact or "").split())
    if not fact:
        raise ValueError("fact must be non-empty")
    if len(fact) > 300:
        fact = fact[:299].rstrip() + "…"
    if redact_secrets(fact) != fact:
        raise ValueError("refusing to store a secret-shaped value in memory")
    mem = load_memory(_SANDBOX_ROOT)
    before = len(mem.facts)
    mem.add_fact(fact)
    if len(mem.facts) == before:
        return "already in memory (skipped duplicate)"
    mem.save()
    return f"remembered: {fact}"


def delete_file(path: str) -> str:
    """Delete a file under the sandbox root.

    The prior content is recorded in the change log so the user can `/undo`
    to restore it. Refuses anything that isn't a regular file (no recursive
    directory removal — that's a footgun the agent shouldn't have).
    """
    p = _resolve(path)
    if not p.is_file():
        raise FileNotFoundError(f"not a file: {path}")
    _hooks.before_tool("delete_file", {"path": path})
    try:
        _changes.current_changelog().record_delete(path, sandbox_root=_SANDBOX_ROOT)
    except Exception:  # noqa: BLE001 - changelog must never block the delete
        pass
    p.unlink()
    return _hooks.after_tool("delete_file", {"path": path}, f"deleted {path}")


def run_shell(cmd: str, timeout: int = 30) -> str:
    """Run a shell command in the sandbox root, blocking until exit.

    Runs through a real shell so the operators models reach for — redirection
    (`>`), pipes (`|`), `&&`/`;`, globs, `$VARS` — work as written. Prefers bash
    when present, falls back to the system shell.

    For long-running commands (dev servers, test suites, installs) use
    `start_background` instead — it returns immediately with a task id.
    """
    import re
    import shutil
    import sys

    _hooks.before_tool("run_shell", {"command": cmd})
    # `open <x>` is macOS; on Linux the equivalent is `xdg-open`. Models reach
    # for `open` out of habit — translate it so it doesn't just fail.
    if sys.platform.startswith("linux") and shutil.which("xdg-open"):
        cmd = re.sub(r"^(\s*)open(\s+)", r"\1xdg-open\2", cmd)
    shell_exe = shutil.which("bash") or None  # None → subprocess uses /bin/sh
    try:
        result = subprocess.run(
            cmd,
            cwd=_SANDBOX_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=True,
            executable=shell_exe,
        )
    except subprocess.TimeoutExpired:
        return f"(timed out after {timeout}s)"
    except FileNotFoundError as e:
        return f"(command not found: {e})"
    out = (result.stdout or "") + (
        f"\n(stderr)\n{result.stderr}" if result.stderr else ""
    )
    out += f"\n[exit {result.returncode}]"
    if len(out) > 8000:
        out = out[:8000] + "\n... (truncated)"
    return _hooks.after_tool("run_shell", {"command": cmd}, out)


# ---------- background tools ----------

def start_background(cmd: str, name: str | None = None, detached: bool = False) -> str:
    """Spawn a background task running `cmd` from the sandbox root.

    Returns the task id (short hex). Use `check_background(id)` to poll,
    `wait_background(id)` to block, `kill_background(id)` to terminate.

    `detached=True` keeps the process alive after the agent exits — useful
    for dev servers you want to keep running.
    """
    mgr = _background.current_manager()
    task = mgr.start(cmd, name=name, detached=detached)
    return (
        f"started task [{task.id}] '{task.name}' (pid={task.pid})"
        if task.is_running
        else f"task [{task.id}] failed to start: {task.status}"
    )


def check_background(task_id: str, tail: int = 30) -> str:
    """Status + recent output of a background task."""
    mgr = _background.current_manager()
    try:
        task = mgr.poll(task_id)
    except KeyError:
        return f"unknown task: {task_id}"
    body = mgr.tail(task_id, lines=tail)
    head = (
        f"[{task.id}] {task.name}  status={task.status}"
        + (f" exit={task.exit_code}" if task.exit_code is not None else "")
        + f"  elapsed={task.elapsed_seconds:.1f}s"
    )
    return head + ("\n" + body if body.strip() else "")


def wait_background(task_id: str, timeout_seconds: float = 60.0) -> str:
    """Block until the task finishes or `timeout_seconds` elapse."""
    mgr = _background.current_manager()
    try:
        task = mgr.wait(task_id, timeout=timeout_seconds)
    except KeyError:
        return f"unknown task: {task_id}"
    if task.is_running:
        return f"[{task.id}] still running after {timeout_seconds:.1f}s"
    return f"[{task.id}] {task.status} (exit {task.exit_code}) in {task.elapsed_seconds:.1f}s"


def kill_background(task_id: str) -> str:
    """Terminate a running background task."""
    mgr = _background.current_manager()
    try:
        task = mgr.kill(task_id)
    except KeyError:
        return f"unknown task: {task_id}"
    return f"[{task.id}] killed (exit {task.exit_code})"


def list_background() -> str:
    """List every known task with status."""
    mgr = _background.current_manager()
    tasks = mgr.poll_all()
    if not tasks:
        return "(no background tasks)"
    lines = []
    for t in tasks:
        suffix = f" exit={t.exit_code}" if t.exit_code is not None else ""
        lines.append(f"[{t.id}] {t.status:<7} {t.name[:50]}  {t.elapsed_seconds:.1f}s{suffix}")
    return "\n".join(lines)


# Tools that require user approval before running.
SIDE_EFFECT_TOOLS = {
    "write_file", "apply_diff", "delete_file", "run_shell",
    "start_background", "kill_background",
}


def register_all() -> None:
    """Register every built-in tool with the SDK's tool registry so the
    `<tool_call>` mechanism can drive them too."""
    sdk_tools.register_tool("read_file", description="read a file from disk")(read_file)
    sdk_tools.register_tool("list_dir", description="list a directory's entries")(list_dir)
    sdk_tools.register_tool("grep", description="search files for a regex")(grep)
    sdk_tools.register_tool("find_files", description="find files by fnmatch name pattern")(find_files)
    sdk_tools.register_tool("glob", description="path-shaped glob from the sandbox root")(glob)
    sdk_tools.register_tool("repo_map", description="ranked map of the codebase's key symbols")(repo_map)
    sdk_tools.register_tool("outline", description="symbols (with signatures) defined in one file")(outline)
    sdk_tools.register_tool("find_symbol", description="where a symbol is defined and referenced")(find_symbol)
    sdk_tools.register_tool("web_fetch", description="fetch a URL and return its text")(web_fetch)
    sdk_tools.register_tool("write_file", description="write a file")(write_file)
    sdk_tools.register_tool("apply_diff", description="replace a unique snippet in a file")(apply_diff)
    sdk_tools.register_tool("edit_symbol", description="replace a function/class by name (AST-anchored)")(edit_symbol)
    sdk_tools.register_tool("delete_file", description="delete a file (undoable)")(delete_file)
    sdk_tools.register_tool("run_shell", description="run a shell command (blocking)")(run_shell)
    sdk_tools.register_tool("remember", description="save one durable project fact to memory")(remember)
    sdk_tools.register_tool("start_background", description="start a background task; returns id")(start_background)
    sdk_tools.register_tool("check_background", description="status + recent output of a task")(check_background)
    sdk_tools.register_tool("wait_background", description="block until a task finishes")(wait_background)
    sdk_tools.register_tool("kill_background", description="terminate a background task")(kill_background)
    sdk_tools.register_tool("list_background", description="list every background task")(list_background)
