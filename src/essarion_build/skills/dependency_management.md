# Dependency management

- **Pin in production, range in libraries.** Applications pin exact versions (lockfile checked in) for reproducible builds. Libraries declare ranges (`>=2,<3`) so consumers can resolve a single compatible version.
- **Use a lockfile.** `pip freeze` is not enough — it loses platform markers and hashes. Use `uv lock`, `poetry.lock`, `pdm.lock`, `npm-shrinkwrap`/`package-lock.json`, `Cargo.lock`. Commit it.
- **Audit on every PR.** `pip-audit`, `npm audit`, `cargo audit`, GitHub Dependabot. CVEs in transitive deps are a real attack vector. Allow-listing a known-false-positive is fine; ignoring everything is not.
- **Minimize the dependency footprint.** Every dep is code you didn't write, license you didn't read, and security surface you didn't audit. "Left-pad" should not be a dep — write the line.
- **Beware abandoned packages.** Last commit two years ago, open PRs ignored, single-maintainer bus factor — risky. Fork-and-vendor is fine if the project is small and stable.
- **License compliance.** Mixing GPL into a proprietary product has consequences. Use a license-checker in CI.
- **Reproducible builds.** Same input → same output. Pin Python/Node versions in `.python-version` / `.nvmrc`. Pin base images by digest, not tag.
- **Upgrades are continuous, not annual.** Stay close to current. The deeper you fall behind, the higher the upgrade tax compounds.
