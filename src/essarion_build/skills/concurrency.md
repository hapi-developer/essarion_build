# Concurrency

- **Pick the right tool.** I/O-bound → `asyncio` or threads. CPU-bound → `multiprocessing` or native code (GIL releases on numpy/syscalls but holds on pure Python). Don't async-ify CPU work; you'll just block the event loop.
- **Shared mutable state is the source of most bugs.** Default to message passing (queues, channels) over shared memory. If you must share state, protect every read and every write with the same lock. Reading "atomic" types without a lock is *not* atomic across multi-instruction operations.
- **The CAP triangle of locks: granularity, ordering, deadlock — pick two.** Coarse locks serialize everything (slow); fine locks compose into deadlocks unless taken in a strict global order.
- **Async hazards.** A blocking call inside an async function (sync I/O, `time.sleep`, CPU-heavy work) halts every coroutine on that loop. Use `asyncio.to_thread` or process pools.
- **Don't mix sync and async without a bridge.** Calling `asyncio.run()` from inside an async function will explode. `nest_asyncio` is a smell.
- **Race conditions hide in TOCTOU.** Time-of-check, time-of-use — the file existed, the user was authorized, the count was below the limit *when you looked*. Either lock across the window or design out the check (atomic compare-and-swap, unique constraints).
- **Test concurrency the hard way.** Property-based tests, fault injection, hypothesis with `stateful` mode. Unit tests almost never reproduce races.
