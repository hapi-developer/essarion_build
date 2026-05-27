# Data modeling

- **Make illegal states unrepresentable.** A `User` whose `email_verified_at` is `None` if and only if `email_verified` is `False` invites bugs. Use a single `verified_at: datetime | None` and derive the bool. In typed languages, prefer ADTs / sealed unions over flag-based modeling.
- **Validate at the boundary, trust inside.** Run input through a schema (pydantic, zod, JSON Schema) at the trust boundary. Code that consumes the validated value should not re-validate.
- **Normalize, then denormalize for performance.** Start in third normal form. Denormalize only when measurement shows a real query problem; document the invariant the denorm depends on.
- **Foreign keys are not optional.** Referential integrity in the database is cheaper than referential integrity in your application code.
- **Time zones.** Store UTC. Convert at display time. Use timezone-aware types (`datetime` with `tzinfo`, never `naive`).
- **IDs.** Prefer opaque tokens (UUIDs, ULIDs) over auto-increment integers for anything user-visible. Sequential IDs leak volume and enable enumeration.
- **Money is not a float.** Use `Decimal` with an explicit scale, or integer minor units (cents).
- **Strings have constraints.** Length, charset, allowed values — encode them in the type system or the schema, not as a comment.
- **Migrations are append-only.** Don't edit applied migrations; write a new one.
