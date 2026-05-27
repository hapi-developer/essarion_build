# Performance

- **Measure before optimizing.** Profilers (`cProfile`, `py-spy`, browser devtools) tell you where time goes; intuition lies. The slow part is usually not where you thought.
- **Algorithmic wins dwarf micro-optimizations.** O(n²) → O(n log n) buys orders of magnitude; replacing a list comprehension with a generator buys microseconds. Get the big-O right first.
- **Common culprits.** N+1 queries (the loop-runs-a-DB-call pattern). Loading whole tables into memory. Re-parsing JSON in a loop. Synchronous I/O on the hot path. Logging at DEBUG with f-strings that eagerly format.
- **Caching: last resort, not first.** A cache adds a coherence problem (when to invalidate) on top of the original problem. Use it when (a) measured slow, (b) result is deterministic for the cache key, (c) staleness is acceptable.
- **Concurrency ≠ speed.** Threads in CPython hit the GIL on CPU-bound work — use `multiprocessing` or native code. Async only helps I/O-bound work. Parallelism without measurement often makes things *slower* due to overhead.
- **Memory matters too.** A 10x memory regression can show up as a 100x slowdown via paging. Watch `RSS`, not just wall time.
- **Benchmark realistic inputs.** Optimizing on a 10-item list when production runs on 10M items teaches you the wrong lesson.

Rule of thumb: make it correct, make it clear, *then* make it fast — and only if measurement says it's slow.
