"""Context builder.

Holds repo files, doc bodies, bundled coding skills, custom user-supplied
skills, focused diffs, and stub interop entries (Sourcipedia topics, Agents
skills). Renders to an XML-ish block the model can read.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Iterable, Self

from pydantic import BaseModel, Field

from ._skills import list_skills, load_skill, load_skills
from .exceptions import ContextError

MAX_FILE_BYTES = 100 * 1024  # files larger than this are skipped


def _read_gitignore(root: Path) -> set[str]:
    """Crude .gitignore reader: literal names + simple globs as suffix matches.

    v0 keeps this simple on purpose. Not a full gitignore implementation.
    """
    ignore: set[str] = set()
    gi = root / ".gitignore"
    if not gi.exists():
        return ignore
    try:
        for line in gi.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            ignore.add(line)
    except OSError:
        pass
    return ignore


def _is_ignored(relpath: str, ignored: set[str]) -> bool:
    parts = relpath.split("/")
    for token in ignored:
        if token in parts:
            return True
        if token.startswith("*.") and relpath.endswith(token[1:]):
            return True
        if relpath == token or relpath.startswith(token.rstrip("/") + "/"):
            return True
    return False


class RepoFile(BaseModel):
    path: str
    content: str


class Doc(BaseModel):
    url: str
    body: str


class Source(BaseModel):
    """Stub Sourcipedia entry. Real wiring lands when the upstream API is exposed."""

    topic: str
    placeholder: str = "<sourcipedia stub — real wiring lands when the API is exposed>"


class AgentSkillRef(BaseModel):
    """Stub reference to an Anthropic Agents API skill manifest. Not loaded in v0."""

    name: str
    placeholder: str = "<agent-skill stub — real loading lands when manifests are public>"


class BuiltinSkill(BaseModel):
    """A bundled coding-practice skill loaded from essarion_build/skills/."""

    name: str
    body: str


class Diff(BaseModel):
    """A focused diff slice: the change set the model should center on."""

    title: str
    body: str


class Context(BaseModel):
    """Builder for the grounding context a Runtime sees.

    Methods return `self` so calls chain. Methods raise ContextError only on
    programmer error (missing path, unknown skill name, network failure on
    add_docs).
    """

    repo_files: list[RepoFile] = Field(default_factory=list)
    docs: list[Doc] = Field(default_factory=list)
    builtin_skills: list[BuiltinSkill] = Field(default_factory=list)
    custom_skills: list[BuiltinSkill] = Field(default_factory=list)
    diffs: list[Diff] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    agent_skills: list[AgentSkillRef] = Field(default_factory=list)

    def add_repo(
        self,
        path: str | Path,
        *,
        include: Iterable[str] | None = None,
        exclude: Iterable[str] | None = None,
        max_files: int | None = None,
    ) -> Self:
        """Add the contents of a repo directory to the context.

        `include` / `exclude` accept gitignore-style globs (fnmatch on the
        relative posix path). When `include` is given, only files matching
        at least one include pattern are loaded. `exclude` patterns always
        win — if a file matches both, it's excluded.

        `max_files` caps the total number of files loaded (in sorted order)
        so a huge repo doesn't blow the token budget.
        """
        root = Path(path).resolve()
        if not root.exists():
            raise ContextError(f"add_repo: path does not exist: {root}")
        if root.is_file():
            raise ContextError(
                f"add_repo: expected a directory, got a file: {root}. "
                "Use add_docs() for a single file."
            )
        ignored = _read_gitignore(root)
        ignored |= {".git", "__pycache__", ".venv", "venv", "node_modules", "dist", "build"}
        include_patterns = list(include) if include else None
        exclude_patterns = list(exclude) if exclude else None

        added = 0
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if _is_ignored(rel, ignored):
                continue
            if exclude_patterns and any(
                fnmatch.fnmatch(rel, pat) for pat in exclude_patterns
            ):
                continue
            if include_patterns and not any(
                fnmatch.fnmatch(rel, pat) for pat in include_patterns
            ):
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            if size > MAX_FILE_BYTES:
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            self.repo_files.append(RepoFile(path=rel, content=text))
            added += 1
            if max_files is not None and added >= max_files:
                break
        return self

    def add_file(self, path: str | Path) -> Self:
        """Load a single file into the context. Convenient for focused tasks."""
        fp = Path(path)
        if not fp.exists() or not fp.is_file():
            raise ContextError(f"add_file: not a file: {fp}")
        try:
            text = fp.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            raise ContextError(f"add_file: could not read {fp}: {e}") from e
        self.repo_files.append(RepoFile(path=fp.as_posix(), content=text))
        return self

    def add_docs(self, url: str) -> Self:
        import httpx

        try:
            response = httpx.get(url, follow_redirects=True, timeout=30.0)
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise ContextError(f"add_docs: failed to fetch {url}: {e}") from e
        self.docs.append(Doc(url=url, body=response.text))
        return self

    def with_skill(self, name: str) -> Self:
        """Load a single bundled coding skill into the context."""
        try:
            body = load_skill(name)
        except FileNotFoundError as e:
            raise ContextError(str(e)) from e
        self.builtin_skills.append(BuiltinSkill(name=name, body=body))
        return self

    def with_skills(self, names: Iterable[str]) -> Self:
        """Load several bundled coding skills into the context."""
        try:
            loaded = load_skills(names)
        except FileNotFoundError as e:
            raise ContextError(str(e)) from e
        for n, body in loaded:
            self.builtin_skills.append(BuiltinSkill(name=n, body=body))
        return self

    def with_all_skills(self) -> Self:
        """Load every bundled coding skill. Convenient default for coding tasks."""
        return self.with_skills(list_skills())

    def with_custom_skill(self, name: str, body: str) -> Self:
        """Inject a user-supplied skill (markdown body) into the context.

        Useful for project-specific guidance: house style, threat model, the
        team's standard `Result<T, E>` pattern. The runtime treats it the
        same as a bundled skill from the model's point of view.
        """
        if not name or not body.strip():
            raise ContextError("with_custom_skill: name and body must be non-empty")
        self.custom_skills.append(BuiltinSkill(name=name, body=body))
        return self

    def with_skills_dir(self, path: str | Path) -> Self:
        """Load every `*.md` file under `path` as a custom skill.

        Skill name is the filename without `.md`. Lets teams keep a folder of
        company-specific skills next to their code.
        """
        root = Path(path)
        if not root.exists() or not root.is_dir():
            raise ContextError(f"with_skills_dir: not a directory: {root}")
        for md in sorted(root.glob("*.md")):
            self.custom_skills.append(
                BuiltinSkill(name=md.stem, body=md.read_text(encoding="utf-8"))
            )
        return self

    def add_diff(self, body: str, *, title: str = "diff") -> Self:
        """Attach a focused diff. The model is instructed to center its
        reasoning on the change rather than the surrounding repo."""
        if not body.strip():
            raise ContextError("add_diff: body must be non-empty")
        self.diffs.append(Diff(title=title, body=body))
        return self

    def add_note(self, note: str) -> Self:
        """Free-form note pinned to the context. Use sparingly — one or two
        sentences at most. Bigger guidance belongs in a custom skill."""
        if not note.strip():
            raise ContextError("add_note: note must be non-empty")
        self.notes.append(note.strip())
        return self

    def add_sourcipedia_topic(self, topic: str) -> Self:
        self.sources.append(Source(topic=topic))
        return self

    def add_agent_skill(self, name: str) -> Self:
        self.agent_skills.append(AgentSkillRef(name=name))
        return self

    def total_chars(self) -> int:
        """Estimate context size (in characters) without rendering."""
        n = 0
        for f in self.repo_files:
            n += len(f.content)
        for d in self.docs:
            n += len(d.body)
        for s in self.builtin_skills:
            n += len(s.body)
        for s in self.custom_skills:
            n += len(s.body)
        for di in self.diffs:
            n += len(di.body)
        for note in self.notes:
            n += len(note)
        return n

    def estimate_tokens(self) -> int:
        """Rough token estimate using the 4-chars-per-token heuristic.

        Not a substitute for the provider's tokenizer, but a useful pre-flight
        check: if `estimate_tokens()` is in the 100k+ range you should trim.
        """
        return max(1, self.total_chars() // 4)

    def to_prompt_block(self) -> str:
        """Render the context as an XML-ish block. Empty sections are omitted."""
        parts: list[str] = ["<context>"]

        if self.builtin_skills or self.custom_skills:
            parts.append("  <skills>")
            for s in self.builtin_skills:
                safe_name = s.name.replace('"', "&quot;")
                parts.append(f'    <skill name="{safe_name}">')
                parts.append(s.body)
                parts.append("    </skill>")
            for s in self.custom_skills:
                safe_name = s.name.replace('"', "&quot;")
                parts.append(f'    <skill name="{safe_name}" source="custom">')
                parts.append(s.body)
                parts.append("    </skill>")
            parts.append("  </skills>")

        if self.notes:
            parts.append("  <notes>")
            for n in self.notes:
                parts.append(f"    <note>{n}</note>")
            parts.append("  </notes>")

        if self.diffs:
            parts.append("  <diffs>")
            for d in self.diffs:
                safe_title = d.title.replace('"', "&quot;")
                parts.append(f'    <diff title="{safe_title}">')
                parts.append(d.body)
                parts.append("    </diff>")
            parts.append("  </diffs>")

        if self.repo_files:
            parts.append("  <repo>")
            for f in self.repo_files:
                safe_path = f.path.replace('"', "&quot;")
                parts.append(f'    <file path="{safe_path}">')
                parts.append(f.content)
                parts.append("    </file>")
            parts.append("  </repo>")

        if self.docs:
            parts.append("  <docs>")
            for d in self.docs:
                safe_url = d.url.replace('"', "&quot;")
                parts.append(f'    <doc url="{safe_url}">')
                parts.append(d.body)
                parts.append("    </doc>")
            parts.append("  </docs>")

        if self.sources:
            parts.append("  <sources>")
            for s in self.sources:
                parts.append(
                    f'    <source topic="{s.topic}">{s.placeholder}</source>'
                )
            parts.append("  </sources>")

        if self.agent_skills:
            parts.append("  <agent_skills>")
            for sk in self.agent_skills:
                parts.append(
                    f'    <agent_skill name="{sk.name}">{sk.placeholder}</agent_skill>'
                )
            parts.append("  </agent_skills>")

        parts.append("</context>")
        return "\n".join(parts)
