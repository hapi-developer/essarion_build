# Database design

- **Indexes follow queries.** Look at your most frequent and most painful queries first; add the index that supports them. Adding indexes blindly costs writes and storage.
- **Composite index order matters.** `(a, b)` serves queries on `a` and on `(a, b)`, but not on `b` alone. Put the equality columns before the range columns.
- **Foreign keys: yes.** They prevent orphans and document the schema. The "performance hit" of FKs is real but small; the cost of orphaned data is much larger.
- **`NULL` is a semantic choice.** Three-valued logic surprises everyone. If a column is "unknown," `NULL` is right. If it's "not yet set but will be," consider a separate `*_at` timestamp instead.
- **Transactions: short and narrow.** Open one, do the smallest correct thing, commit. Long transactions cause lock contention and replication lag.
- **Isolation level.** Most apps run fine on `READ COMMITTED`. If you need stronger, you usually need `SERIALIZABLE` (Postgres) or explicit locks — don't pick from the middle without knowing the anomalies.
- **Migrations.** Append-only. Never edit an applied migration. Plan for backwards-compatibility across deploys: add column → backfill → switch reads → switch writes → remove old column, across multiple releases.
- **Backups: only valid if you've restored one.** Untested backups are wishes.
- **`SELECT *` in application code is a future bug.** Add a column and your serialization breaks. Be explicit.
- **N+1.** The query-in-a-loop pattern. Fix with a join, a `WHERE id IN (...)`, or an ORM `.prefetch_related`/`.includes`.
