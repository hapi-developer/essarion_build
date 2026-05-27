# Documentation

- **Write for the audience that will read it.** Library users want examples and reference. Operators want runbooks. Contributors want architecture. Don't conflate them in one document.
- **The first thing a reader sees should answer "what is this and why would I use it?"** Five-line elevator pitch at the top of every README. Then install, then a working example, then reference.
- **Working code beats prose.** A copy-paste example that runs is worth 500 words. If the example doesn't run, it's worse than nothing.
- **Document the *contract*, not the implementation.** "Returns the user's preferred locale" survives a refactor; "reads `users.locale` from Postgres" doesn't.
- **Comments in code: only when WHY is non-obvious.** What it does is the code's job. Why this *particular* approach exists — a workaround for a specific bug, a hidden invariant, a subtle perf trick — that's a comment.
- **No docstrings on trivial functions.** A docstring on `def add(a, b): return a + b` is noise. Save them for the surface API and anything that surprised you while writing.
- **Keep docs near the code they describe.** Inline docstrings for API reference, top-level `docs/` for narratives and ADRs. Wikis decay fastest because they're farthest from the code.
- **Date or version stamp anything that ages.** Tutorials that say "as of v2.3" are honest; tutorials that just rot are hostile.
- **Diagrams: when text fails.** Sequence and architecture diagrams for things that are inherently spatial. Plain text for the rest.
