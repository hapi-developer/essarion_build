# Scope discipline

Most production bugs come from changes that did more than they had to.

- **Solve the stated problem, not the adjacent ones.** If the task is to fix a date-parsing bug, the diff should change the date parser. Renaming a nearby function, reformatting a file, "while I'm here" cleanups — those belong in separate PRs (or no PR at all).
- **No drive-by refactors.** Even good cleanups, mixed with a fix, hide the fix from the reviewer and from `git blame`. Stage them.
- **Don't add features.** "I noticed we could also support X" is the death-by-thousand-cuts pattern. Note it for later; ship the fix.
- **No premature abstraction.** "We might need this to be configurable" — you don't, until you do. Three callers with diverging needs is when you abstract.
- **No defensive code for impossible states.** Don't add `if user is None:` to a function that's only called with a verified user. Trust internal callers; check at the boundary.
- **Avoid backward-compat shims when you can just change the code.** A real backward-compat constraint (public API, persistent data) is one thing; a phantom one ("someone might depend on this") is just deferred technical debt.
- **Delete dead code completely.** Don't rename `_var` to `_unused_var`; don't leave `// TODO removed for now`. Delete it. The history has it.
- **A bug fix doesn't need surrounding cleanup. A one-shot operation doesn't need a helper.**

The discipline of doing *exactly* what was asked, no more and no less, compounds. It makes reviews faster, blames cleaner, and rollbacks safer.
