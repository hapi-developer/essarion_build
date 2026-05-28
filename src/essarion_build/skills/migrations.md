# Migrations (schema and data)

- **Migrations are forward-only at the surface.** Don't ship a "down" migration users will run in production. If you must roll back, roll forward with a corrective migration.
- **One change per migration.** "Add column" and "backfill" are separate migrations. "Add column" and "drop another column" are separate migrations. Tiny migrations apply fast, fail safely, and review cleanly.
- **Backwards-compatible deploys.** Old code must work against the new schema, and new code must work against the old schema (until everyone's on the new code). The recipe:
  1. Add the new column (nullable) — old code ignores it; new code can write it.
  2. Backfill — usually in batches, with throttling.
  3. Switch reads to the new column.
  4. Stop writes to the old column.
  5. Drop the old column (in a later release).
- **Big tables: avoid `ALTER TABLE` that rewrites.** On Postgres, `ADD COLUMN` with a constant default is fine after v11; `ADD COLUMN NOT NULL DEFAULT <volatile>` rewrites the whole table. On MySQL, plan for online DDL or `gh-ost`. Test on production-sized data, not your laptop.
- **Index creation is online when possible.** `CREATE INDEX CONCURRENTLY` (Postgres) — no lock; doesn't block writes. The non-concurrent version blocks all writes; production-fatal.
- **Backfill in idempotent batches.** Resumable, throttled, observable. A backfill that runs for 6 hours then crashes leaves you with no idea what's done; a batched backfill has a clear cursor.
- **Lock timeouts on every migration.** Default to a few seconds; if you can't acquire the lock that fast, the migration is dangerous and should be retried during a quieter window. A 6-hour `ALTER TABLE` that holds a table lock is an outage.
- **Test the migration on a copy of production.** Sample size, distribution, and constraint shape all matter. "Works on a 1k-row dev DB" is not evidence for a 100M-row prod table.
- **Data migrations: dry-run + diff before commit.** Generate the SQL, log the affected rows, review *what changed* before applying. UPDATE without a WHERE has happened more than once.
- **Migration history is your data model's git log.** Order matters; never edit applied migrations. New migrations get new names; you only fix forward.
- **Coordinate with the team.** A migration that ships at 5 PM Friday and runs during morning peak is everyone's problem. Use a deploy window or a feature-flag-gated rollout.
