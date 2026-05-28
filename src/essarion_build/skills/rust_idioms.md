# Rust idioms

- **`Result<T, E>` over panics for recoverable errors.** Panics are for invariant violations the caller cannot fix; `Result` is for outcomes the caller can branch on. Use `?` to bubble; never `.unwrap()` in library code.
- **Custom error types via `thiserror` for libraries.** Library callers want to match on error variants; `anyhow::Error` blurs that. Use `thiserror` for the public seam and `anyhow` only at the binary's edges.
- **Borrow first, own when forced.** `&str` over `String` in arguments unless you must own. `Cow<'_, str>` when sometimes-borrowed-sometimes-owned. Cloning early is a code smell; profile before optimizing.
- **`Option::map` / `Result::map` over match for one-line transforms.** `x.map(|v| v + 1)` reads better than `match x { Some(v) => Some(v + 1), None => None }`. But use `match` (or `if let`) when the arms aren't symmetric.
- **Newtype to lock units and IDs.** `struct UserId(u64)` prevents `fn delete(id: u64)` from silently accepting a `PostId`. Cheap, free at runtime, infinite payoff in correctness.
- **Lifetimes follow data flow.** When the compiler asks for `'a`, the borrow you're returning is tied to an input. Don't sprinkle lifetimes to "make it compile" — figure out which input it's borrowing from.
- **Iterators over `for` + `Vec::push` accumulation.** `.collect::<Vec<_>>()` is idiomatic; `iter().filter().map().sum()` is more efficient than the imperative version *and* easier to read.
- **`#[non_exhaustive]` on public enums you'll grow.** Lets you add variants without a major-version break.
- **Concurrency: `Send + Sync` are guarantees, not annotations.** If the compiler refuses, the data really isn't safe to share — fix the data structure, don't `unsafe impl Sync`.
- **Cargo.lock: check in for binaries, gitignore for libraries.** Binaries need a reproducible build; libraries need their consumers to resolve.
- **`clippy --all-targets -- -D warnings` in CI.** Treat clippy lints as errors locally too; they catch real bugs (not just style).
