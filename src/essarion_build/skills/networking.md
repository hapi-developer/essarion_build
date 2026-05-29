# Networking

- **Set a timeout on every network call.** Without one, a hung server takes your worker offline indefinitely. Read timeout AND connect timeout, both explicit. `requests.get(url, timeout=(5, 30))`, `httpx.Timeout(...)`.
- **Retries with backoff + jitter, capped attempts.** Two retries with `1s, 2s, 4s` jittered. Without jitter, every client retries in lockstep and you have a self-DDoS. With unbounded retries, transient outages compound.
- **Retry only on retriable errors.** 429, 502, 503, 504, connection error, read timeout — yes. 400, 401, 403, 422, 404 — no. Retrying a 401 is just adding load to a server that's already telling you "no".
- **Idempotency keys on write endpoints.** Clients retry; servers must dedupe. The client sends a UUID per logical request; the server stores it for some window and returns the original response on replay.
- **Connection pooling at scale.** TCP handshake is expensive at high QPS; reuse connections. `httpx.Client()` (not `httpx.get()` per call), `requests.Session()`, etc. Set max-connections per host so you don't exhaust the remote.
- **TLS verification ON, always.** `verify=False` is for a controlled local test only — never in production. If a cert is invalid, surface the error; don't paper over it.
- **Pin the TLS version to ≥1.2.** TLS 1.0 / 1.1 are deprecated; many providers reject them outright. Most languages default to 1.2+ now, but verify on legacy stacks.
- **Don't log secrets in network traces.** Auth headers, query-string tokens, body fields with passwords — all need a redaction layer in your logger. Easier to redact at the source than to scrub logs later.
- **Headers matter.** `User-Agent` so the remote can identify you; `Accept-Encoding: gzip` for bandwidth; `Content-Type` set correctly. Missing `Accept` headers cause 415s in strict APIs.
- **Streaming for big bodies.** Don't load a 4 GB download into memory. `requests.get(..., stream=True)` and iterate; `httpx.stream(...)`. Same for uploads.
- **DNS is part of your latency budget.** Cold-cache lookups can take 100 ms+. Long-lived connections amortize this; sidecar resolvers cache it.
- **Observability per call: duration, status, retries.** A flaky upstream is best identified by "5% of calls take 2× the median"; without histograms you'll never see it.
- **Be a good citizen: respect `Retry-After`.** When the server says "wait 30s", wait 30s. Tight retry loops are how you become a DoS attack.
