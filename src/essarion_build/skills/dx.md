# Developer experience (DX)

DX is the friction between an engineer's intent and a shipped change. Every minute spent fighting tools is a minute not spent solving the user's problem.

- **Fast feedback wins.** Test runs in seconds, not minutes. Type-check on save, not on push. Hot-reload, not "kill server and restart". Slow feedback compounds: every PR has dozens of feedback loops.
- **One command to set up the repo.** `make bootstrap` or `./scripts/setup` clones, installs, builds, and runs tests. New engineers shouldn't read a 30-step README to land their first commit.
- **One command for everything in the common path.** `make test`, `make lint`, `make fmt`, `make run`. Memorize five verbs; build muscle memory.
- **Editor integration is part of the toolchain.** LSP / Language Server, format-on-save, lint diagnostics inline. If "lint" is a CLI-only experience, half the issues will be caught at PR time instead of typing time.
- **Errors are the most-read documentation.** A confusing error message ("Error: undefined") wastes thousands of person-hours across users; a helpful one ("Error: missing field `name` at config.json:14 — did you mean `Name`?") saves them. Invest accordingly.
- **CI replicates locally.** `act` for GitHub Actions, Docker Compose for the integration stack. Debugging "works on my machine, fails in CI" is friction with no upside.
- **PR feedback under 24 hours.** Faster is better, but 24h is the cap before context decays and the author moves on. Owned by the on-call reviewer, not "whoever notices".
- **Documentation lives in the repo, runs in CI.** Markdown is just text; "the docs" is what people search the codebase for. Inline examples; doctest where possible; broken-link check in CI.
- **Onboarding is a feature.** Pair a new engineer through their first ten merges. The friction they hit is the DX backlog.
- **Time-to-first-commit is a metric.** From clone to merged PR — measure it for new joiners. Cut it.
- **Delete more than you add.** Every unused config, abandoned script, dead test, and aspirational TODO costs people time. Aggressively prune.
