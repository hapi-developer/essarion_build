# Build systems

- **Deterministic builds win.** Same inputs → same outputs, every time. Pin everything: package versions, toolchain version, OS image. Reproducibility is the foundation of trustworthy CI, secure supply chain, and "rebuild from a tag two years later".
- **Lock files are the contract.** `package-lock.json`, `poetry.lock`, `Cargo.lock`, `go.sum`. Commit them for applications; commit-or-not for libraries depending on the ecosystem's norm. Pip without a lock is whack-a-mole on transitive deps.
- **Cache aggressively, invalidate correctly.** A CI build that takes 20 minutes from scratch but 3 minutes incrementally is the difference between "PRs flow" and "CI is the bottleneck". Cache by lock-file hash; rebuild when it changes.
- **Hermetic when possible.** No network during the build. No reading from /etc. No shelling out to git for the version (read it from an env var the CI passes in). Hermetic builds are reproducible; non-hermetic builds are mysteries.
- **Incremental builds need correct dependency tracking.** If `make` thinks `b.o` only depends on `b.c` but it also depends on `b.h`, you get stale builds. Either use a build system that tracks (`bazel`, `cmake -B`, `ninja`), or run clean builds and accept the cost.
- **Build outputs go in a clean directory.** `dist/`, `build/`, `target/`. Don't sprinkle artifacts among the source. `git clean -fdx` should restore a pristine checkout.
- **Generated code: commit it OR generate it in CI.** Not both. "Sometimes committed, sometimes regenerated" leads to diffs nobody understands.
- **Multi-target: one source tree, many artifacts.** Library, CLI, container, lambda — all built from the same source with different targets. Bazel / pants / Nx if the matrix is huge; a Makefile or `scripts/build*` if it's small.
- **Build observability.** Time each step. The slowest 10% of steps usually dominate total time, and you can only fix what you measure. Cache hit rates matter too.
- **Reproducible across machines.** Devcontainer / nix / asdf — pick one. "Works on my machine, breaks on CI" usually means the machine differs from CI in a way the build system doesn't catch.
- **One-command build.** `make build`, `bazel build //...`, `cargo build`. If new contributors need a PDF of instructions to compile, you've lost.
- **CI as code.** `.github/workflows/`, `gitlab-ci.yml`, etc. Reviewable, versioned, testable. Click-ops in the CI UI bypasses your code review.
