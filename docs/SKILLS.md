# Bundled skills index

Quick reference for the 54 skills shipped with `essarion-build`. Each
skill is a short markdown brief loaded into the context block when you
call `Context.with_skill(name)` or `Context.with_all_skills()`.

## Language-specific

- `python_idioms` — comprehensions, generators, EAFP, context managers, dataclasses
- `typescript_idioms` — strict mode, narrowing, never-types, satisfies
- `rust_idioms` — Result/Option, ownership, lifetimes, newtype, clippy
- `go_idioms` — interfaces in/structs out, goroutines need owners, context
- `sql_idioms` — parameterization, explicit columns, indexing, NULL semantics

## Frontend

- `react_patterns` — hooks correctness, server/client state, key stability
- `state_management` — sources of truth, atomic updates, derived state, hydration
- `accessibility` — semantic HTML, keyboard, focus, contrast, screen-reader testing
- `internationalization` — ICU plurals, locale formatting, RTL layout, UTF-8

## Backend / systems

- `api_design` — verb/noun separation, error shapes, versioning, idempotency
- `database_design` — normalization, indexing, transactions, foreign keys
- `data_modeling` — domain types, value objects, identifiers, schemas as contracts
- `migrations` — forward-only, online DDL, batched backfills, rollback paths
- `caching` — invalidation strategies, TTL, stampede mitigation, browser HTTP
- `microservices` — start monolithic, business-capability boundaries, sagas
- `event_driven` — events vs commands, schema evolution, idempotent consumers
- `distributed_systems` — CAP in practice, logical clocks, backpressure
- `networking` — timeouts, retries with jitter, idempotency, TLS, headers

## Cross-cutting practices

- `secure_coding` — input validation, output encoding, secrets, crypto defaults
- `web_security` — CSP, cookies, CSRF, CORS, HSTS, JWT pitfalls, SSRF
- `auth_security` — sessions, MFA, OAuth, token rotation, account security
- `error_handling` — explicit failures, no silent swallow, error context
- `concurrency` — locks, atomics, channels, deadlock avoidance, race patterns
- `performance` — measure first, hot path focus, complexity vs constant factors
- `observability` — logs/metrics/traces, SLOs, alert hygiene
- `observability_practice` — RED+USE, correlation IDs, cardinality, runbooks
- `logging` — structure, levels, redaction, sampling, retention

## Engineering process

- `code_review` — correctness, readability, scope, security, performance
- `code_review_practice` — approval bar, PR size, nit/question/blocker, async
- `testing` — golden path, edge cases, fast feedback, integration boundaries
- `debugging` — minimal repro, bisect, hypothesis-test cycles, log carefully
- `refactoring` — preserve behavior, small steps, test after each, name first
- `scope_discipline` — solve the stated problem, no drive-by changes
- `documentation` — audience, runnable examples, what+why, freshness
- `code_organization` — change-locality, acyclic deps, public surface vs `_`
- `code_style` — formatter as style guide, linter as quality gate, naming
- `code_smells` — long params, feature envy, primitive obsession, god class
- `code_search` — start from user path, tests as docs, git log/blame, narrow
- `dependency_injection` — pass deps, constructor over global, test seams
- `dependency_management` — pin, audit, automate upgrades, lockfiles

## Infrastructure & ops

- `cloud_infra` — IaC, least privilege, tagging, multi-AZ, secrets, backups
- `kubernetes` — requests/limits, liveness vs readiness, rolling updates
- `containers` — one process, multi-stage, pinned digests, non-root user
- `build_systems` — deterministic, lock files, cache+invalidate, hermetic
- `release_engineering` — trunk-based, semver, changelog, canary, immutable
- `incident_response` — mitigate first, declare early, IC roles, blameless
- `feature_flags` — release vs experiment vs ops, kill switches, removal
- `git_workflow` — clean history, atomic commits, descriptive messages
- `dx` — fast feedback, one-command setup, errors as docs, ship-time metric

## AI / data / specialty

- `llm_integration` — prompt injection, structured outputs, tool-use limits
- `code_with_llms` — read every diff, anchor with file:line, scope discipline
- `ml_engineering` — data is the product, splits, baselines, reproducibility
- `cli_design` — composition, flag conventions, exit codes, signal handling
- `agile_practice` — working code, smallest releasable change, time-box

## Total

54 bundled skills. Add your own via `Context.with_custom_skill(name, body)`
or `Context.with_skills_dir(path)`.
