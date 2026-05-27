"""Context builder.

Holds repo files, doc bodies, bundled coding skills, and stub interop
entries (Sourcipedia topics, Agents skills). Renders to an XML-ish block
the model can read.
"""

from __future__ import annotations

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


class Context(BaseModel):
    """Builder for the grounding context a Runtime sees.

    Methods return `self` so calls chain. Methods raise ContextError only on
    programmer error (missing path, unknown skill name, network failure on
    add_docs).
    """

    repo_files: list[RepoFile] = Field(default_factory=list)
    docs: list[Doc] = Field(default_factory=list)
    builtin_skills: list[BuiltinSkill] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    agent_skills: list[AgentSkillRef] = Field(default_factory=list)

    def add_repo(self, path: str | Path) -> Self:
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

        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if _is_ignored(rel, ignored):
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

    def add_sourcipedia_topic(self, topic: str) -> Self:
        self.sources.append(Source(topic=topic))
        return self

    def add_agent_skill(self, name: str) -> Self:
        self.agent_skills.append(AgentSkillRef(name=name))
        return self

    def to_prompt_block(self) -> str:
        """Render the context as an XML-ish block. Empty sections are omitted."""
        parts: list[str] = ["<context>"]

        if self.builtin_skills:
            parts.append("  <skills>")
            for s in self.builtin_skills:
                safe_name = s.name.replace('"', "&quot;")
                parts.append(f'    <skill name="{safe_name}">')
                parts.append(s.body)
                parts.append("    </skill>")
            parts.append("  </skills>")

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
