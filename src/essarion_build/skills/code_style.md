# Code style

- **The formatter is the style guide.** `black` / `prettier` / `gofmt` / `rustfmt`. Run it pre-commit; never argue about whitespace in review again. Pick one and live with its choices.
- **Linter as a quality gate, not a nag.** Treat lint failures like test failures: red CI, blocked merge. Pin the linter version; don't let the rules drift between checkouts.
- **One concept per line.** Long chains read better broken across lines (one method per line). Boolean expressions with three predicates: extract well-named locals. The goal is "read top-to-bottom like English"; rules below serve that.
- **Names carry intent.** `count` ≠ `total` ≠ `n_items`. `users` (collection) ≠ `user` (instance) ≠ `user_id` (identifier). When a name is hard to pick, the abstraction is wrong, not the name.
- **Booleans answer the question their name asks.** `is_ready`, `has_payment_method`, `should_retry`. Not `flag`, `valid`, `enabled` (enabled for what?).
- **Symmetry signals correctness.** `open_file` / `close_file`. `acquire_lock` / `release_lock`. If the pair looks asymmetric, something's wrong (often: missing error handling).
- **Comment WHY, not WHAT.** The code already says what; if it's not clear, rename. Comments explain the why a reader can't infer: hidden constraint, subtle invariant, workaround for upstream bug #1234.
- **Docstrings on public functions; not on every closure.** Docstrings are for callers. Internal helpers with obvious names don't need them.
- **No dead code.** Commented-out blocks, unreachable branches, unused imports. The version control system remembers; the codebase shouldn't.
- **Function length: as short as honest.** A 200-line function with three concerns is often three 70-line functions waiting to be born; but a 200-line function doing one coherent thing is fine.
- **Avoid the temptation to "improve" code you don't need to touch.** Drive-by refactors balloon PR review costs. Land the bug fix; file the refactor for later.
- **Newlines as paragraph breaks.** A blank line separates concerns; a single line within a paragraph means "same idea, next step". Densely packed code without breaks is a wall.
