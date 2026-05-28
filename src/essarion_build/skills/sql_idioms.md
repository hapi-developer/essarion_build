# SQL idioms

- **Parameterized queries always.** Never concatenate user input. `WHERE id = $1`, not `WHERE id = '" + id + "'`. SQL injection is a solved problem; the only way to lose is to skip the parameters.
- **Be explicit in `SELECT`.** Avoid `SELECT *` in code — the schema can drift under you and add a column you don't want streamed back. Name the columns you read.
- **Joins: `INNER JOIN ... ON` over comma joins.** Modern syntax is clearer, lets the planner work, and surfaces missing join keys at parse time.
- **Index for the queries you actually run.** Look at the slow-query log; add indexes for `WHERE` / `JOIN` / `ORDER BY` columns that show up. Composite-index column order matters: leftmost is queryable on its own.
- **Transactions for multi-statement consistency.** `BEGIN`/`COMMIT`. Always wrap state-changing sequences. Pick the isolation level deliberately — `READ COMMITTED` for most OLTP, `SERIALIZABLE` for things like "transfer money".
- **`NULL` is not equal to anything, including itself.** `WHERE x = NULL` returns nothing. Use `IS NULL` / `IS NOT NULL`. Same for `NOT IN (… NULL …)`.
- **Schema migrations are append-only at the surface.** Add a nullable column with a default; backfill; then add the constraint. Never drop a column the application still reads.
- **Aggregate carefully.** `COUNT(col)` skips nulls; `COUNT(*)` doesn't. `SUM(col)` returns `NULL` on empty sets (use `COALESCE(SUM(col), 0)`).
- **`LIMIT` without `ORDER BY` is non-deterministic.** Almost always a bug. Order by a primary key or a stable composite to get reproducible results.
- **Window functions over self-joins for top-N-per-group.** `ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY ts DESC)` beats a self-join + group-by every time.
- **`EXPLAIN` before optimizing.** Trust the planner's verdict, not your intuition. A seq scan on 100 rows is faster than an index lookup.
