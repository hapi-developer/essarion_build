# Release engineering

- **Trunk-based, short-lived branches.** Long-lived feature branches are merge-conflict factories and integration-bug incubators. Merge to main daily; gate features with flags.
- **Every commit on main is releasable.** CI green ≠ ready; "passes lint, tests, build, integration, and security scans" = ready. If "ready" requires manual steps, automate them.
- **Semantic versioning is a public contract.** `MAJOR.MINOR.PATCH` — break, add, fix. Pre-1.0 you can move fast; post-1.0, breaking changes need a deprecation cycle.
- **Changelogs are for humans.** Keep-a-Changelog format. Group by version, then by Added / Changed / Fixed / Removed / Security. Auto-generated dumps of commit messages are not changelogs.
- **Release notes ≠ changelog.** Changelog is exhaustive; release notes are curated for users ("here's what matters in this release").
- **Tag the commit you released.** Annotated tag, signed if you're doing sig verification. The tag is the public artifact; never move it after publish.
- **Reproducible builds.** Same inputs → same outputs. Pin every dependency (lockfile checked in for binaries), pin the toolchain (Dockerfile / asdf / nix). "It built last week" must mean it builds today.
- **Artifacts are immutable.** Once you've published `1.2.0`, never republish under that version. Yank if needed; publish a new version with the fix.
- **Rollback is a feature; design for it.** Database migrations must be reversible (or paired with a forward-fix path); deployments must be revertible without rebuilding. The rollback drill is part of pre-release testing.
- **Canary / progressive rollout.** Deploy to 1%, then 10%, then 100%. Watch error rates and SLO burn at each step. Halt and rollback if metrics drift.
- **Supply-chain hygiene.** SBOM, signed commits, signed artifacts (Sigstore / cosign), provenance attestation. Dependabot or Renovate to keep upstream fresh.
- **Release calendar is a real artifact.** When did 1.2.0 ship? Who owned it? Was the canary clean? What broke and how was it fixed? This is the data postmortems need.
