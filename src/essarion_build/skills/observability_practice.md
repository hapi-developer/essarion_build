# Observability in practice

A pragmatic complement to `observability` and `logging`. About *how* to ship observable systems, not what to log.

- **Three pillars: logs, metrics, traces. Pick the right one per question.** Logs answer "what happened on this specific request." Metrics answer "is the system in a healthy state right now." Traces answer "where in this multi-service call did the time go." Reaching for the wrong one wastes hours.
- **Correlation IDs everywhere.** Every request gets a request_id propagated to every log, every span, every downstream call. Without it, debugging a multi-service failure is impossible. Generate at the edge; pass through; log on every entry/exit.
- **Cardinality kills.** A metric labeled by user_id explodes your time-series DB. Labels are dimensions you'll *aggregate over* — env, region, status_code. High-cardinality IDs go in logs (or traces), never in metric labels.
- **RED metrics for every service.** Rate (requests / second), Errors (errors / second OR percent), Duration (p50 / p95 / p99). Three numbers per endpoint. Skip these and you're flying blind.
- **USE metrics for every resource.** Utilization (% busy), Saturation (queue depth), Errors (rejections). Three numbers per CPU / disk / connection pool / thread pool.
- **Span on the boundaries.** Every cross-service call gets a span; every DB query gets a span. Don't span individual function calls — the noise drowns out the signal. Add span attributes for the dimensions you'll want to slice on: user.tier, endpoint, region.
- **Alert on symptoms, not causes.** "CPU > 90% on host X" is rarely actionable. "Login error rate > 1%" is what you actually care about. Alerts that page someone need a runbook and a clear customer impact.
- **SLOs over SLAs over hope.** SLO is your internal target. SLA is the contractual one. SLOs drive burn-rate alerts: page when you're burning the budget too fast, not at first error.
- **Logs are structured or they're noise.** `logger.info("user_action", user_id=..., action=...)` is queryable; `logger.info(f"user {u} did {a}")` is grep-bait. JSON in production logs; the cost is paid back the first time you have an outage.
- **Logs are write-once. Treat them like an append-only stream.** Don't try to update a log later. If a request changes state, emit a new log line; tracing connects them via the request ID.
- **Sampling for traces, full logs for errors.** 1% sampling of traces keeps cost manageable; force-sample on errors so you always have the failing case. Logs: log every error fully; sample successes.
- **Synthetic transactions.** A bot that hits your critical user flow every minute. When real users break, the synthetic breaks first; you find out from the alarm, not from the support ticket.
- **The "debug in prod" muscle is real.** Practice it before you need it: distributed tracing UI, log query syntax, runbook lookup. The first time you reach for these during an incident should not be the first time you've used them.
