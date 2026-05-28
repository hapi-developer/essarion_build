# Microservices

- **Start with a monolith.** Microservices solve organizational scaling problems (separate deploys, separate teams), not "code quality" problems. If you split too early, you get distributed mud.
- **Service boundaries follow business capabilities**, not technical layers. "Orders", "Inventory", "Billing" — yes. "Database service", "API service", "Logic service" — no.
- **Each service owns its data.** No cross-service database joins. If service B needs data from A, B asks A's API or A publishes events B subscribes to. The moment two services share a table, you have a distributed monolith with the worst of both worlds.
- **Async messaging for cross-service writes; sync RPC for cross-service reads when latency matters.** Saga / outbox patterns for "do A and B atomically when A and B are different services". Don't roll your own 2PC.
- **Idempotency keys on every write API.** Networks lose answers, not requests. Clients retry; servers must dedupe.
- **Contract tests at every boundary.** Pact, or consumer-driven contract tests in CI. "Works in dev" doesn't survive when you redeploy provider and consumer separately.
- **Distributed tracing is mandatory, not optional.** Without `traceparent` propagation you cannot debug a slow request across 5 services. OpenTelemetry; auto-instrument when possible; log the trace ID on every error.
- **Circuit breakers + timeouts + retries with backoff.** Every cross-service call. Without circuit breakers, one slow service takes down its callers; without timeouts, your goroutines/threads pile up.
- **Versioning the wire format is forever.** Use additive changes (new optional fields), never breaking ones. When you absolutely must break, run two versions in parallel until the slowest consumer migrates.
- **Observability per service: health, readiness, RED metrics (Rate / Errors / Duration).** Health is "I'm alive"; readiness is "I can serve traffic"; they're different and both must exist for safe rolling deploys.
- **Don't share the same auth library across services with different update cadences.** A vulnerability in one service shouldn't require updating eleven others to patch it. Shared, then forked, is fine.
- **The cost of microservices is operations.** Logging, tracing, deploys, secret management, service discovery, network policy. Budget for it before you split the first service.
