# Caching strategy

- **Cache invalidation is the hard part.** Decide *up front* how an entry becomes stale: TTL, explicit invalidation, version key, or read-through. "We'll figure it out later" produces ghost data forever.
- **TTL is a lower bound on staleness, not an SLA.** A 60s TTL means data can be 60s old *and then some*, until the next read. If freshness is contractual, you need explicit invalidation or write-through.
- **Read-through vs write-through.** Read-through (lazy): cache populated on first miss; simple, but cold-start latency. Write-through: cache updated synchronously with the source of truth; fast reads, costlier writes. Pick deliberately.
- **Cache stampede / dog-pile is real.** When a hot key expires, every request hits the origin. Mitigations: probabilistic early expiration (`xfetch`), single-flight (only one fetcher per key), lock-then-fetch, or tiered TTLs with jitter.
- **Cache keys are part of your API.** Changing the key space silently invalidates everything; document it like any other contract. Include a version prefix so you can rev safely.
- **Negative caching matters too.** "404 not found" should be cached briefly to keep one missing row from melting your DB; not for as long as a hit, but not zero either.
- **Don't cache PII in shared layers.** Browser-side fine; CDN-side or shared Redis: think about it (especially with cookies / `Authorization` headers — vary on them or skip the cache).
- **Browser caching is HTTP semantics, not a feature.** `Cache-Control: public, max-age=…`, `ETag`, `Last-Modified`, `Vary` are the contract. Get them right and you get a free CDN.
- **Memoization is a cache too.** Bound it (LRU with a max size) or you have a memory leak that grows with traffic.
- **Observability before tuning.** Hit ratio, eviction rate, p99 latency on cache hits vs misses. You can't reason about cache effectiveness without numbers.
- **The fastest cache is not having one.** Before caching, ask whether the underlying query / computation can be made fast enough. Caches add complexity; sometimes a better index removes the need entirely.
