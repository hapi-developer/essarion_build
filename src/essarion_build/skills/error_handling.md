# Error handling

- **Raise at the boundary where you can do nothing useful; handle where you can.** If a function can't recover, let the exception propagate. Catching to log-and-re-raise is noise; catching to swallow is a bug. Catching to *recover* (fallback, retry, alternate path) is the only good reason.
- **Specific over broad.** `except FileNotFoundError:` not `except Exception:`. Bare `except:` is almost always wrong — it swallows `KeyboardInterrupt` and `SystemExit`.
- **Error types form an API.** Define an exception hierarchy callers can catch by category. A library exposing only `ValueError` makes callers grep your messages — coupling them to strings.
- **Don't validate scenarios that can't happen.** Trust internal code and framework guarantees. Only check at trust boundaries (user input, external APIs, deserialization).
- **Retry only idempotent operations.** Read-after-write, transient 5xx on GET — yes. POST a payment — no, unless you have an idempotency key. Exponential backoff with jitter; cap the attempts.
- **Error messages.** State what went wrong, what the inputs were (minus secrets), and what the caller can do. Avoid "An error occurred." Include enough context to be actionable.
- **Don't catch and log without re-raising or recovering.** That's how silent failures happen.
