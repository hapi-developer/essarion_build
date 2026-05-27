# CLI design

- **Follow POSIX/GNU conventions.** Short flags `-v`, long flags `--verbose`, `--` to stop flag parsing, `-` for stdin/stdout. Users have decades of muscle memory; don't reinvent.
- **Subcommands for verbs, flags for options.** `git commit -m "..."`, not `git --commit --message "..."`. The verb-first structure scales.
- **Sensible defaults.** Running with no args should either do the most common thing or print helpful usage. Never silently do something destructive.
- **Idempotent where possible.** `mkdir -p`, `rm -f` — friendly to scripts. Erroring on "already exists" forces every caller to wrap in a try/check.
- **Exit codes are an API.** `0` = success, non-zero = failure. Different non-zero codes for different failure classes (usage error vs runtime error vs network error). Document them.
- **Output goes to stdout; diagnostics go to stderr.** This is what lets pipes work: `mytool | grep foo` should only see the data.
- **Machine-readable mode.** `--json` or `--format=json` for scripts; pretty/colored for humans (default when stdout is a TTY, plain when piped — `isatty` check).
- **Be quiet by default.** Verbose output is opt-in. Tools that print "Processing file 1..." by default are noise.
- **Help that helps.** `--help` shows usage and examples, not just a list of flags. `tool subcommand --help` is per-subcommand.
- **Confirm destructive operations** unless `--yes` / `-y` is passed. Reversibility is the test — `rm` confirms because there's no undo.
- **Progress for slow operations.** A spinner or progress bar tells the user "I'm alive." Silent multi-minute waits invite ctrl-C.
