# Code review

What a reviewer looks for, in priority order:

1. **Does it solve the stated problem?** Read the PR description and the diff. If the diff does more or less than the description, that's the first comment.
2. **Correctness.** Walk through one happy path and two edge cases mentally. Check off-by-one, null/None handling, empty collections, concurrency races.
3. **Security.** New input boundary? Auth check present? Secrets handled? SQL parameterized? See `secure_coding`.
4. **Tests.** Are the new branches covered? Do the tests actually exercise the new behavior or just the framework? Would the tests fail if you reverted the change?
5. **Naming.** Can you guess what a function/variable does from the name? Bad names are technical debt with compound interest.
6. **Scope.** Does the PR also rename unrelated things, reorganize imports, "fix" formatting? Those belong in separate PRs.
7. **Readability.** Long functions, deep nesting, magic numbers, dead code, commented-out code — call them out.
8. **Style and nits.** Last, and clearly labeled "nit:" so the author knows it's optional.

Tone: assume good faith, ask questions before asserting, suggest concretely ("could be `dict.get` with a default"). LGTM-with-nits is fine; refusing to approve over preferences is not.

The goal is to ship the right change, not to win the comment thread.
