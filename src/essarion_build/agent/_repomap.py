"""Repo map & symbol index — structural understanding of the codebase.

This gives the model an Aider-style **repo map**: a compact, PageRank-ranked
outline of the project's most important symbols (classes, functions + their
signatures), fit to a token budget, plus on-demand symbol tools (`outline`,
`find_symbol`). The point is the same edge Aider gets — the model sees the
*globally important* API surface cheaply, so it asks for the right files
instead of blind-grepping, and it knows a symbol exists before reinventing it.

Design constraints that matter here:

* **Pure standard library.** Python files are parsed with `ast` (as precise as
  tree-sitter for Python); other languages fall back to a small regex
  def-table. No tree-sitter, no networkx — PageRank is ~25 lines of power
  iteration. Breadth degrades gracefully; it never hard-fails a turn.
* **mtime-cached.** Parsing every file each turn would be wasteful, so each
  file's tags are cached on `(path, mtime, size)` and only re-parsed when it
  changes — the same trick Aider uses with diskcache.

References: Aider's repo map (https://aider.chat/2023/10/22/repomap.html),
AutoCodeRover's structure-aware search (arXiv:2404.05427), Agentless
hierarchical localization (arXiv:2407.01489).
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# Resolved once: lets us honour the project's real .gitignore (via
# `git check-ignore`) so generated/vendored files don't pollute the map.
_GIT = shutil.which("git")

# Directories we never descend into — VCS, dependency, and build caches. The
# walk would otherwise spend all its time in node_modules.
_IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env", "dist",
    "build", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".idea", ".tox",
    "target", ".next", ".cache", "vendor", ".gradle", "bin", "obj",
}

# Extension → language key. "python" is parsed with `ast`; the rest use the
# regex def-table below. Anything not listed is skipped for the map.
_LANG_BY_EXT = {
    ".py": "python", ".pyi": "python",
    ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js",
    ".ts": "js", ".tsx": "js",
    ".go": "go", ".rs": "rust", ".rb": "ruby",
    ".java": "java", ".kt": "java", ".cs": "java", ".scala": "java",
    ".c": "c", ".h": "c", ".cpp": "c", ".cc": "c", ".hpp": "c",
    ".php": "php", ".swift": "swift",
}

# Per-language definition patterns. Each entry is (regex, kind). The first
# capture group is the symbol name. Deliberately conservative — favouring
# precision (fewer false "defs") over recall, since refs are token-scanned.
_DEF_PATTERNS: dict[str, list[tuple[re.Pattern[str], str]]] = {
    "js": [
        (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)"), "class"),
        (re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\("), "function"),
        (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>"), "function"),
        (re.compile(r"^\s*(?:export\s+)?(?:type|interface)\s+([A-Za-z_$][\w$]*)"), "type"),
    ],
    "go": [
        (re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\("), "func"),
        (re.compile(r"^\s*type\s+([A-Za-z_]\w*)\s+"), "type"),
    ],
    "rust": [
        (re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)"), "fn"),
        (re.compile(r"^\s*(?:pub\s+)?struct\s+([A-Za-z_]\w*)"), "struct"),
        (re.compile(r"^\s*(?:pub\s+)?enum\s+([A-Za-z_]\w*)"), "enum"),
        (re.compile(r"^\s*(?:pub\s+)?trait\s+([A-Za-z_]\w*)"), "trait"),
    ],
    "ruby": [
        (re.compile(r"^\s*class\s+([A-Z]\w*)"), "class"),
        (re.compile(r"^\s*module\s+([A-Z]\w*)"), "module"),
        (re.compile(r"^\s*def\s+([A-Za-z_]\w*[!?=]?)"), "def"),
    ],
    "java": [
        (re.compile(r"^\s*(?:public|private|protected|\s)*(?:final\s+|abstract\s+)?(?:class|interface|enum)\s+([A-Za-z_]\w*)"), "class"),
        (re.compile(r"^\s*(?:public|private|protected)\s+(?:static\s+)?[\w<>\[\],.\s]+\s+([A-Za-z_]\w*)\s*\("), "method"),
    ],
    "c": [
        (re.compile(r"^\s*(?:class|struct)\s+([A-Za-z_]\w*)"), "type"),
        (re.compile(r"^[A-Za-z_][\w\s\*<>,:&]*?\b([A-Za-z_]\w*)\s*\([^;]*\)\s*\{"), "function"),
    ],
    "php": [
        (re.compile(r"^\s*(?:abstract\s+|final\s+)?class\s+([A-Za-z_]\w*)"), "class"),
        (re.compile(r"^\s*(?:public|private|protected|static|\s)*function\s+([A-Za-z_]\w*)\s*\("), "function"),
    ],
    "swift": [
        (re.compile(r"^\s*(?:public\s+|private\s+|open\s+)?(?:final\s+)?(?:class|struct|enum|protocol)\s+([A-Za-z_]\w*)"), "type"),
        (re.compile(r"^\s*(?:public\s+|private\s+)?func\s+([A-Za-z_]\w*)"), "func"),
    ],
}

_IDENT_RE = re.compile(r"\b[A-Za-z_]\w{2,}\b")
_MAX_FILES = 4000        # cap the walk on giant monorepos
_MAX_BYTES = 800_000     # skip files larger than this (generated/minified)


@dataclass
class Defn:
    """One definition the model might care about: a class/function/etc."""

    name: str
    kind: str            # class | def | function | method | type | …
    line: int            # 1-based line of the definition
    end_line: int        # 1-based last line (defs only; signatures otherwise)
    signature: str       # rendered head, e.g. "def process(self, x) -> int"


@dataclass
class _FileTags:
    """Cached parse of one file: its definitions and the names it references."""

    defs: list[Defn] = field(default_factory=list)
    refs: set[str] = field(default_factory=set)


# (abs_path) -> (mtime, size, tags). Survives across turns within a process.
_TAG_CACHE: dict[str, tuple[float, int, _FileTags]] = {}


# --------------------------------------------------------------------------- #
# Tag extraction                                                              #
# --------------------------------------------------------------------------- #

def _py_signature(node: ast.AST) -> str:
    """Render a compact, single-line signature head for a Python def/class."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        try:
            args = ast.unparse(node.args)
        except Exception:  # noqa: BLE001 - older/edge ASTs
            args = ", ".join(a.arg for a in node.args.args)
        ret = ""
        if node.returns is not None:
            try:
                ret = f" -> {ast.unparse(node.returns)}"
            except Exception:  # noqa: BLE001
                ret = ""
        return f"{prefix} {node.name}({args}){ret}"
    if isinstance(node, ast.ClassDef):
        bases = []
        for b in node.bases:
            try:
                bases.append(ast.unparse(b))
            except Exception:  # noqa: BLE001
                pass
        return f"class {node.name}" + (f"({', '.join(bases)})" if bases else "")
    return ""


def _py_tags(text: str) -> _FileTags:
    """Extract defs (with signatures + line spans) and referenced names from
    a Python source string using the standard-library `ast`."""
    tags = _FileTags()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return tags  # unparseable → no tags, never raise

    def visit(node: ast.AST, cls: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kind = "class" if isinstance(child, ast.ClassDef) else ("method" if cls else "def")
                start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                name = f"{cls}.{child.name}" if cls and not isinstance(child, ast.ClassDef) else child.name
                tags.defs.append(Defn(
                    name=name, kind=kind, line=start,
                    end_line=getattr(child, "end_lineno", child.lineno) or child.lineno,
                    signature=_py_signature(child),
                ))
                visit(child, child.name if isinstance(child, ast.ClassDef) else cls)
            else:
                visit(child, cls)

    visit(tree, None)
    # References: every Name load and attribute access.
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            tags.refs.add(n.id)
        elif isinstance(n, ast.Attribute):
            tags.refs.add(n.attr)
    return tags


def _regex_tags(text: str, lang: str) -> _FileTags:
    """Extract defs via the per-language regex table; references via a generic
    identifier scan. Less precise than `ast` but dependency-free for the long
    tail of languages."""
    tags = _FileTags()
    patterns = _DEF_PATTERNS.get(lang, [])
    for i, line in enumerate(text.splitlines(), start=1):
        if len(line) > 400:  # minified / data line
            continue
        for rx, kind in patterns:
            m = rx.match(line)
            if m:
                tags.defs.append(Defn(
                    name=m.group(1), kind=kind, line=i, end_line=i,
                    signature=line.strip()[:120],
                ))
                break
    for m in _IDENT_RE.finditer(text):
        tags.refs.add(m.group(0))
    return tags


def _tags_for(path: Path) -> _FileTags:
    """Return cached tags for `path`, re-parsing only if it changed on disk."""
    lang = _LANG_BY_EXT.get(path.suffix.lower())
    if lang is None:
        return _FileTags()
    try:
        st = path.stat()
    except OSError:
        return _FileTags()
    if st.st_size > _MAX_BYTES:
        return _FileTags()
    key = str(path)
    cached = _TAG_CACHE.get(key)
    if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
        return cached[2]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return _FileTags()
    tags = _py_tags(text) if lang == "python" else _regex_tags(text, lang)
    _TAG_CACHE[key] = (st.st_mtime, st.st_size, tags)
    return tags


# --------------------------------------------------------------------------- #
# Index                                                                       #
# --------------------------------------------------------------------------- #

@dataclass
class RepoIndex:
    """A scanned snapshot of the repo's symbols, ready to rank and query."""

    root: Path
    defs_by_file: dict[str, list[Defn]] = field(default_factory=dict)
    refs_by_file: dict[str, set[str]] = field(default_factory=dict)
    # symbol name (last dotted segment) -> set of files that define it
    def_files: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    def files(self) -> list[str]:
        return list(self.defs_by_file)


def _gitignored(root: Path, rels: list[str]) -> set[str]:
    """The subset of `rels` the project's .gitignore excludes, via
    `git check-ignore`. Correct gitignore semantics (incl. global excludes), and
    untracked-but-not-ignored new files are kept. Empty set when git is absent or
    `root` isn't a repo — so the walk degrades to the built-in ignore dirs."""
    if not rels or _GIT is None:
        return set()
    try:
        proc = subprocess.run(
            [_GIT, "-C", str(root), "check-ignore", "--stdin"],
            input="\n".join(rels), capture_output=True, text=True,
            timeout=10, check=False,
        )
    except Exception:  # noqa: BLE001 - never let ignore-checking break a scan
        return set()
    if proc.returncode not in (0, 1):  # 128 → not a repo / error
        return set()
    return {ln.strip() for ln in proc.stdout.splitlines() if ln.strip()}


def _iter_source_files(root: Path):
    """Yield source files under `root`, skipping ignored dirs and anything the
    project's .gitignore excludes, up to `_MAX_FILES`."""
    candidates: list[Path] = []
    for p in sorted(root.rglob("*")):
        if len(candidates) >= _MAX_FILES:
            break
        if not p.is_file():
            continue
        if any(part in _IGNORE_DIRS for part in p.relative_to(root).parts[:-1]):
            continue
        if p.suffix.lower() not in _LANG_BY_EXT:
            continue
        candidates.append(p)
    ignored = _gitignored(root, [p.relative_to(root).as_posix() for p in candidates])
    for p in candidates:
        if p.relative_to(root).as_posix() not in ignored:
            yield p


def build_index(root: str | Path) -> RepoIndex:
    """Scan every source file under `root` and collect its symbol tags."""
    root = Path(root).resolve()
    idx = RepoIndex(root=root)
    for p in _iter_source_files(root):
        rel = p.relative_to(root).as_posix()
        tags = _tags_for(p)
        if not tags.defs and not tags.refs:
            continue
        idx.defs_by_file[rel] = tags.defs
        idx.refs_by_file[rel] = tags.refs
        for d in tags.defs:
            idx.def_files[d.name.split(".")[-1]].add(rel)
    return idx


# --------------------------------------------------------------------------- #
# Ranking — pure-Python PageRank over the symbol def/ref graph                #
# --------------------------------------------------------------------------- #

def _pagerank(
    out_edges: dict[str, list[tuple[str, float]]],
    nodes: list[str],
    personalization: dict[str, float] | None = None,
    damping: float = 0.85,
    iterations: int = 30,
) -> dict[str, float]:
    """Weighted PageRank via power iteration. `out_edges[src]` is a list of
    `(dst, weight)`; rank flows from a file to the files it depends on."""
    n = len(nodes)
    if n == 0:
        return {}
    if personalization:
        total = sum(personalization.get(x, 0.0) for x in nodes) or 1.0
        teleport = {x: personalization.get(x, 0.0) / total for x in nodes}
    else:
        teleport = {x: 1.0 / n for x in nodes}
    rank = {x: 1.0 / n for x in nodes}
    out_sum = {src: sum(w for _, w in edges) for src, edges in out_edges.items()}
    for _ in range(iterations):
        nxt = {x: (1.0 - damping) * teleport[x] for x in nodes}
        dangling = 0.0
        for x in nodes:
            if out_sum.get(x, 0.0) <= 0:
                dangling += rank[x]
        for src, edges in out_edges.items():
            s = out_sum.get(src, 0.0)
            if s <= 0:
                continue
            share = damping * rank[src]
            for dst, w in edges:
                if dst in nxt:
                    nxt[dst] += share * (w / s)
        # Dangling nodes (no out-edges) redistribute by teleport.
        for x in nodes:
            nxt[x] += damping * dangling * teleport[x]
        rank = nxt
    return rank


def rank_symbols(
    idx: RepoIndex, *, focus: set[str] | None = None
) -> list[tuple[float, str, Defn]]:
    """Rank every definition by structural importance.

    Builds a file graph (A→B when A references a symbol B defines), runs
    PageRank — personalized toward `focus` files when given — then scores each
    symbol by its file's rank times how widely the symbol is referenced.
    Returns `(score, file, Defn)` tuples, highest first.
    """
    nodes = idx.files()
    if not nodes:
        return []
    nodeset = set(nodes)
    out_edges: dict[str, list[tuple[str, float]]] = defaultdict(list)
    # How many distinct files define each short name (for the privacy/ubiquity
    # multipliers, mirroring Aider's weighting).
    def_breadth = {name: len(files) for name, files in idx.def_files.items()}
    for src, refs in idx.refs_by_file.items():
        seen: dict[str, float] = {}
        for name in refs:
            targets = idx.def_files.get(name)
            if not targets:
                continue
            mul = 1.0
            if name.startswith("_"):
                mul *= 0.1                       # private — less interesting
            if len(name) >= 8 and re.search(r"[A-Z_]", name[1:]):
                mul *= 2.0                       # long, multi-word — API-ish
            if def_breadth.get(name, 1) > 5:
                mul *= 0.2                       # ubiquitous (utils) — dampen
            w = mul
            for dst in targets:
                if dst == src or dst not in nodeset:
                    continue
                seen[dst] = seen.get(dst, 0.0) + w
        for dst, w in seen.items():
            out_edges[src].append((dst, w))
    personalization = {f: 1.0 for f in (focus or set()) if f in nodeset} or None
    rank = _pagerank(out_edges, nodes, personalization=personalization)

    # How many files reference each short name — the real importance signal.
    # Precomputed once (O(total refs)) so scoring stays O(defs) on big repos.
    ref_file_count: dict[str, int] = defaultdict(int)
    for rs in idx.refs_by_file.values():
        for nm in rs:
            ref_file_count[nm] += 1

    scored: list[tuple[float, str, Defn]] = []
    for rel, defs in idx.defs_by_file.items():
        base = rank.get(rel, 0.0)
        boost = 5.0 if (focus and rel in focus) else 1.0
        own_refs = idx.refs_by_file.get(rel, set())
        for d in defs:
            short = d.name.split(".")[-1]
            users = ref_file_count.get(short, 0) - (1 if short in own_refs else 0)
            penalty = 0.15 if short.startswith("_") else 1.0
            score = base * boost * (1 + max(users, 0)) * penalty
            scored.append((score, rel, d))
    scored.sort(key=lambda t: (-t[0], t[1], t[2].line))
    return scored


# --------------------------------------------------------------------------- #
# Rendering                                                                   #
# --------------------------------------------------------------------------- #

def render_map(
    idx: RepoIndex, *, focus: set[str] | None = None, budget_chars: int = 6000
) -> str:
    """Render a compact, ranked repo map that fits within `budget_chars`.

    Greedily includes the highest-ranked symbols until the budget is hit, then
    groups them by file (files ordered by their best symbol) so the output
    reads like a table of contents.
    """
    scored = rank_symbols(idx, focus=focus)
    if not scored:
        return ""
    chosen: dict[str, list[Defn]] = defaultdict(list)
    file_order: list[str] = []
    used = 0
    for _score, rel, d in scored:
        if rel not in chosen:
            file_order.append(rel)
            used += len(rel) + 4
        line = f"    {d.signature or (d.kind + ' ' + d.name)}"
        used += len(line) + 1
        if used > budget_chars and chosen:
            break
        chosen[rel].append(d)
    lines = [
        "repo map — most important symbols (ranked). Use `outline <file>`, "
        "`find_symbol <name>` or read_file for detail.",
    ]
    for rel in file_order:
        defs = chosen.get(rel)
        if not defs:
            continue
        lines.append(f"  {rel}")
        for d in sorted(defs, key=lambda x: x.line):
            sig = d.signature or f"{d.kind} {d.name}"
            lines.append(f"    {sig}  ·L{d.line}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Query helpers (back the outline / find_symbol tools)                        #
# --------------------------------------------------------------------------- #

def outline_text(root: str | Path, rel: str) -> str:
    """A symbol outline for one file: classes/functions + signatures + lines."""
    p = (Path(root) / rel).resolve()
    tags = _tags_for(p)
    if not tags.defs:
        return f"(no symbols found in {rel})"
    lines = [f"outline {rel} ({len(tags.defs)} symbols):"]
    for d in sorted(tags.defs, key=lambda x: x.line):
        indent = "    " if "." in d.name else "  "
        lines.append(f"{indent}{d.signature or (d.kind + ' ' + d.name)}  ·L{d.line}")
    return "\n".join(lines)


def find_references(root: str | Path, name: str, *, exclude: str | None = None,
                    max_hits: int = 40) -> list[tuple[str, int, str]]:
    """Word-boundary search for `name` across source files. Returns
    `(rel, line, text)`. Precise enough for find-references / impact analysis
    without an LSP, and language-agnostic."""
    root = Path(root).resolve()
    rx = re.compile(rf"\b{re.escape(name)}\b")
    hits: list[tuple[str, int, str]] = []
    for p in _iter_source_files(root):
        rel = p.relative_to(root).as_posix()
        if exclude and rel == exclude:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if name not in text:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if rx.search(line):
                hits.append((rel, i, line.strip()[:160]))
                if len(hits) >= max_hits:
                    return hits
    return hits


def find_symbol_text(root: str | Path, name: str) -> str:
    """Where is `name` defined, and where is it used? Definitions (with
    signatures) followed by reference sites — the go-to-definition +
    find-references the model would otherwise burn many greps to reconstruct."""
    root = Path(root).resolve()
    idx = build_index(root)
    short = name.split(".")[-1]
    matches: list[tuple[str, Defn]] = []
    for rel, defs in idx.defs_by_file.items():
        for d in defs:
            if d.name == name or d.name.split(".")[-1] == short:
                matches.append((rel, d))
    out: list[str] = []
    if matches:
        out.append(f"{name}: {len(matches)} definition(s)")
        for rel, d in sorted(matches, key=lambda t: (t[0], t[1].line)):
            out.append(f"  {rel}:{d.line}  {d.signature or (d.kind + ' ' + d.name)}")
    else:
        out.append(f"{name}: no definition found in the index")
    # Drop reference lines that are the definitions themselves.
    def_sites = {(rel, d.line) for rel, d in matches}
    refs = [(rel, ln, tx) for rel, ln, tx in find_references(root, short, max_hits=40)
            if (rel, ln) not in def_sites]
    if refs:
        more = " (truncated)" if len(refs) >= 40 else ""
        out.append(f"referenced at {len(refs)} site(s){more}:")
        out.extend(f"  {rel}:{ln}: {tx}" for rel, ln, tx in refs)
    else:
        out.append("no other references found")
    return "\n".join(out)
