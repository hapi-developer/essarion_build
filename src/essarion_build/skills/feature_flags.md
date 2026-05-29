# Feature flags

- **Every risky change goes behind a flag.** Schema migrations, new endpoints, behavior changes that affect billing or auth. The cost of adding a flag is hours; the cost of a bad rollout to 100% of users is a weekend.
- **Flag types are different.** Release flags (short-lived; remove after rollout). Experiment flags (A/B testing; remove after analysis). Operational flags (long-lived; for kill switches). Permission flags (forever; entitlement-based). Confusing them creates flag debt.
- **Default to OFF in production code, ON in tests.** Code paths behind a flag still need test coverage; flip the flag in test setup. The unflagged default in code must be the safe one.
- **Flag evaluation is a hot path.** Cache locally with a SDK; never RPC per-request to the flag service. Streaming updates from the service so caches converge in seconds.
- **Granularity matters.** Per-user / per-account / per-region targeting. Percentage rollouts. Whitelists for internal testing first. Always have an "everyone off except these IDs" mode for emergencies.
- **Kill switches are flags, but the inverse direction.** "Disable the new checkout if the conversion rate drops 5%." Wire them to your monitoring so on-call can flip without redeploying.
- **Removing a flag is a project, not a chore.** Delete the old branch fully — code, tests, telemetry. Stale flags accumulate and turn the codebase into a maze of `if (flag(...)) { ... } else { ... }`.
- **Audit every flag change.** Who, when, what value, what scope. Comes up every postmortem; cheap to log.
- **Never gate database writes on a client-side flag.** The client can be tampered with. Server checks the flag; client UI follows the same flag for consistency, but the security boundary is server-side.
- **Flag rollout is observable.** When you ramp from 1% to 10%, you must be able to read error rates and latency *for the flagged cohort specifically*. Without that, ramps are blind.
- **Test the flag-off and flag-on paths in CI.** Both branches are production code. A bug in the unreachable branch is still a bug — it lands the day someone flips the flag.
