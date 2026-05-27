# Git workflow

- **One logical change per commit.** Not "two changes that happened to be in my working copy." If you can describe the commit with the word "and," split it.
- **Commit messages.** Imperative subject ("Add idempotency token to /payments", not "Added"). 50-char subject, blank line, body wrapping at 72. The body explains *why*, not *what* — the diff already shows what.
- **Rebase your branch, merge to main.** A linear history per branch is readable; a tangled main history is not. `git pull --rebase` for branch updates.
- **Don't force-push to shared branches.** `--force-with-lease` on your own branch, never on main/master.
- **Pull requests stay small.** ~400 lines of diff is a soft ceiling. Larger PRs get less rigorous review and ship more bugs.
- **PR description.** Problem, approach, what was tried and rejected, how to verify. Reviewers spend more time understanding context than reading code.
- **Don't commit secrets, large binaries, or generated files.** Use `.gitignore`. If a secret slips in, rotate it — git history is forever; redaction tooling is hard.
- **Tags for releases.** Semantic versioning. Annotated tags (`-a`), not lightweight.
- **`.gitattributes` for line endings and binary handling.** Cross-platform teams that skip this learn the hard way.

Good Git hygiene is a multiplier on team velocity — bad hygiene compounds into archaeology.
