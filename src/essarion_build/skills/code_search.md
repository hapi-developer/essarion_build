# Code search

How to find what you're looking for in an unfamiliar codebase.

- **Search by signal, not by guess.** Symbol names in identifier search; phrases in full-text. `grep -rn "stripe.Charge.create"` finds Stripe usage faster than reading the README.
- **Start from the user's path.** Where does the user click? What URL gets hit? Trace from `routes.py` (or equivalent) into handlers, then into services. The call graph is usually clearer top-down than middle-out.
- **Tests are documentation.** When you don't know what a function does, find its tests. They show inputs, outputs, edge cases. Often clearer than the function itself.
- **Recent commits reveal intent.** `git log -p --since="3 months" path/to/file` shows what's been changing — and the commit messages explain why. Often more useful than the current code alone.
- **`git blame` tells you who to ask.** The author of the line you don't understand has a Slack handle. A 30-second message saves hours of archaeology.
- **Reference graph: who calls X.** `grep -rn "X("` is the lazy version; an LSP-driven `find references` is the right one. Knowing the call sites helps you reason about impact and edge cases.
- **Multiple passes, narrowing each time.** Pass 1: skim everything for shape. Pass 2: read the data structures. Pass 3: read the hot path. Don't try to understand it all on the first pass.
- **Look for naming conventions.** `_private` vs public, `handle_*` vs `process_*`, `*Service` vs `*Repository`. Conventions encode where logic lives.
- **Find the smallest reproducer.** "It's slow" → narrow to a function → narrow to a query → narrow to a row. Each narrowing is faster to test than the last.
- **`pytest --co -q` (or your equivalent) lists every test.** Browsing test names gives a quick map of what the code can do without reading any source.
- **When in doubt, run it.** Add a print, run the failing test, see what's actually happening. Five minutes of running it can replace an hour of reading.
- **Build the mental model in a doc.** Write down what you've learned as you learn it. A scratch markdown file with the architecture you're piecing together. The act of writing forces precision.
