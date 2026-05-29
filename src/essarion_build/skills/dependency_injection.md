# Dependency injection

- **Pass dependencies in; don't reach for them.** A function that needs the DB takes a `db` argument; it doesn't `import db_singleton`. Hidden dependencies are the #1 reason "the test imports work but the integration test hangs".
- **Constructor over setter over global.** Required deps go in the constructor (compiler/type checker enforces). Optional deps can be setters. Globals (and singletons) are last resort and need a damn good reason.
- **Test seams: every external system has one.** A `Storage` protocol, a `Clock` protocol, a `RandomSource` protocol — even when there's only one production implementation. Lets tests run without S3, without `time.sleep`, and without flakey randomness.
- **DI containers are great… until they aren't.** A simple service graph is fine without one — just wire it in `main`/`app_factory`. Reach for `wired`, `dependency-injector`, `inject` only when the graph is genuinely complex.
- **Scopes are part of the design.** Singleton (process lifetime), per-request (web), per-test (test setup). Mixing scopes accidentally — a singleton that closes its connection per request — is a hard-to-debug class of bug.
- **Mocks are a smell, not a tool.** If you're mocking the database to test the data-access layer, you're not testing the data-access layer. Use a real test DB (sqlite, testcontainers); mock only at the system boundary (the HTTP client, the message bus).
- **Beware over-abstraction.** Three implementations? Worth an interface. One implementation that will never have a second? Inline it; you'll thank yourself later.
- **Construction order matters.** If A depends on B and B depends on A you have a cycle; the runtime will tell you, but design should have caught it. Untangle by introducing a third object both depend on (event bus, repository).
- **Service locator is not dependency injection.** "Pass the container" hides what's actually needed and prevents the type checker from helping. If your tests need to "configure the container per test" you've recreated the global-state problem.
- **Async + DI: async constructors are awkward.** Prefer a sync `__init__` that stores connection strings, plus an async `connect()` that does the I/O. Resources own their own lifecycle.
- **In tests, build the smallest possible object graph for what's under test.** A fixture that constructs the universe to test one function is a fixture that breaks when anything in the universe changes.
