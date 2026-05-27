# API design

Whether REST, RPC, GraphQL, or a Python library — the same principles apply.

- **Names are the API.** A renamed function is a breaking change for callers. Pick the name you'll be happy with in two years.
- **Make the easy case easy and the hard case possible.** A default-everything `client.send(message)` should work; advanced users reach for kwargs. If the only way to use it is the advanced way, the API is wrong.
- **Be parsimonious with required arguments.** Each required arg is a thing a caller must understand. Optional kwargs with sensible defaults push the cognitive cost to readers who care.
- **Idempotency.** `PUT` and `DELETE` should be safe to retry. `POST` is not idempotent unless the caller provides an idempotency key. Document which is which.
- **Errors are part of the API.** Specify the error types (or HTTP statuses) callers can expect. Don't sprinkle new exception types in a patch release — that breaks except-clauses.
- **Versioning.** SemVer or date-based, but be deliberate. Breaking changes deserve a major bump and a migration note. Add fields freely; never remove or repurpose.
- **Pagination, filtering, sorting.** Plan for them on day one for list endpoints — retrofitting is painful.
- **Document the contract, not the implementation.** "Returns the user's preferred locale" is the contract; "reads `users.locale` from Postgres" is the implementation and may change.
