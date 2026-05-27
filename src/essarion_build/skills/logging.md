# Logging

- **Structured, not free-form.** JSON logs with explicit fields (`level`, `msg`, `request_id`, `user_id`, …) are grep-able, parse-able, and queryable. `print("user 42 did thing")` is none of those.
- **Levels mean things:**
  - `DEBUG` — diagnostic detail for developers. Off in production by default.
  - `INFO` — normal operational events worth a record (startup, shutdown, key state changes).
  - `WARNING` — recoverable problem or upcoming issue (deprecation, rate-limit approached).
  - `ERROR` — operation failed; user-visible or data-affecting.
  - `CRITICAL` — service is down or about to be.
  If everything is INFO you have no signal; if everything is ERROR you have alert fatigue.
- **One log line per logical event.** Not five lines per event scattered across functions. Build a context dict and log once at the boundary.
- **Never log secrets, tokens, full PII, or full request bodies.** Redact in the formatter, not at every call site. Assume logs leak.
- **Correlation IDs.** Inject a `request_id` (or `trace_id`) at the entry point and propagate it through every log line and downstream call. Debugging a multi-service request without one is misery.
- **Don't log and re-raise.** Pick one. Logging in a handler that re-raises produces duplicate lines for the same event.
- **Sample the noisy stuff.** A million `INFO`s about cache hits is just expensive paper. Sample at 1% with a count tag.
- **Test that your formatter doesn't crash on edge inputs** (non-UTF8, nested dicts with cycles, very large strings). A logging crash on an error path is a wide-area outage.
