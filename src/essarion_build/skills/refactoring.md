# Refactoring

- **Refactor *before* the change, not as part of it.** A refactor PR that also adds a feature is two PRs in one; the reviewer can't tell which line is which. Land the refactor first, then add the behavior on top.
- **Three similar lines is better than a premature abstraction.** Wait until the pattern is established and the shape is obvious. A function with one caller is misnamed inlined code.
- **Smells worth extracting:** long argument lists (>4), deep nesting (>3 levels), repeated literal strings, "switch on type" cascades, comments explaining what a block does (the block wants to be a function with that comment as its name).
- **Smells worth inlining:** functions called once that don't have a meaningful name beyond restating the code, helpers passed through three layers untouched, type aliases that just rename `str`.
- **Behavior-preserving means tests pass on both sides.** Run the suite before and after. If you don't have tests for the area you're refactoring, add them *first*, then refactor.
- **Don't refactor speculatively.** "We might need this to be generic someday" is the call of the YAGNI siren. Generic-on-day-one costs flexibility tomorrow because the wrong joints are frozen.
- **Renames are cheap and high-value.** A function whose name lies is worse than no name. If you read code and the name surprised you, that's the refactor.
