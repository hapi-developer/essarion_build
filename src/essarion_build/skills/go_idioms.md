# Go idioms

- **Errors are values; return them, don't panic.** Wrap with `fmt.Errorf("doing X: %w", err)` and unwrap with `errors.Is` / `errors.As`. Panics are for unreachable invariant violations only.
- **Accept interfaces, return structs.** Functions take the smallest interface they need; producers return concrete types so callers can extend. `io.Reader` in, `*bytes.Buffer` out.
- **Goroutines need an owner.** Every goroutine has a clear lifetime; never spawn-and-forget. Use `context.Context` to cancel and `sync.WaitGroup` (or `errgroup.Group`) to join.
- **`context.Context` is the first arg of every request-scoped function.** Pass it through; never store it in a struct. Always check `ctx.Err()` at long-running boundaries.
- **`defer` for resource cleanup, paired with the acquisition.** `f, err := os.Open(...)`; check `err`; then `defer f.Close()`. Don't `defer` in loops without thinking — defers stack until the function returns.
- **Zero values should be useful.** `var b bytes.Buffer` is ready to write. Design your types so the zero value isn't a footgun.
- **Channels for ownership transfer, mutexes for state.** Channel: "I'm done with this; you take it." Mutex: "many readers/writers share this state." Don't mix.
- **`go vet` + `staticcheck` + `golangci-lint` in CI.** They catch real bugs (lock copies, format-string mismatches, ignored errors).
- **Slices share backing arrays.** Passing `s[:n]` to a function that appends can clobber a caller's slice. When in doubt, `append` into a fresh slice or use `slices.Clone`.
- **`go.mod` minimum version is a contract.** Don't bump it casually; downstream is pinned to it.
- **Generics for collections; interfaces for behavior.** Don't reach for generics when an interface composes more clearly.
- **Tests live next to code (`_test.go`).** Use table-driven tests with `t.Run(name, …)` for clear failure output.
