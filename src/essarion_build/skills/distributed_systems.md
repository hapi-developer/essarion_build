# Distributed systems

- **Networks fail. So do clocks, disks, and processes.** Build assuming partitions, packet loss, reordering, and duplicates. "It worked in my local dev" is not evidence of correctness in distributed code.
- **The CAP theorem is real but rarely a daily concern.** In practice you pick between latency and consistency on every read path. Document the choice; users get angry when "eventually" turns out to be longer than they assumed.
- **Idempotency is non-negotiable.** Anything that can be retried (which is everything) must be safe to apply twice. Operation IDs at the request level; dedupe windows on the receive side.
- **Avoid distributed transactions; embrace sagas.** 2PC is fragile and slow at scale; sagas (sequence of local transactions + compensating actions on failure) are how big systems coordinate. Plan the compensations before you ship the happy path.
- **Clocks lie. Use logical clocks for ordering.** Lamport timestamps, vector clocks, Hybrid Logical Clocks. "Wall clock 14:32:15.123" is fine for logs; never for "which write came first?"
- **Consensus is expensive. Don't reach for Raft/Paxos when you have a single leader and can fence on lease.** Most systems get away with much simpler primitives — a Postgres row, a Zookeeper lock — until they really can't.
- **Backpressure flows upstream.** If a downstream is slow, upstream must slow down (drop, queue with bound, or 503). Without backpressure, your queue grows until OOM.
- **Health checks ≠ correctness.** "Service responds 200" is necessary, not sufficient. Synthetic transactions that exercise the full path catch problems shallower probes miss.
- **Set deadlines, not retries.** A 30s deadline propagating through 5 services is shared budget; if 4 of them took 25s, the fifth shouldn't bother. Without deadline propagation, retries cascade into thundering herds.
- **Failure isolation: bulkheads + circuit breakers.** A slow database shouldn't be allowed to consume every thread/connection in the calling service. Per-dependency thread pools or semaphores; circuit breakers that open under sustained error rates.
- **Chaos testing should be routine, not theatrical.** Game days where you actually shut something down. A system that's never been tested under failure isn't fault-tolerant; it just hasn't failed yet.
- **Read-your-writes vs. monotonic reads — make the guarantee explicit.** Users notice when they save a thing and then can't see it for 200ms. Sticky sessions, read-from-primary windows, or version vectors solve it; "don't worry, it's eventually consistent" doesn't.
- **Heartbeat + lease, not heartbeat + ping.** A lease that expires under partition lets the surviving side make progress; a ping that just times out leaves the system stuck.
