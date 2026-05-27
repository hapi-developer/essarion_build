# Secure coding

Defaults to apply on every change that touches input, output, or secrets.

- **Validate at boundaries.** User input, network input, file input, and IPC are untrusted. Validate type, length, range, and shape *before* the value crosses into trusted code. Do not validate again ten frames deep — that hides the boundary.
- **Encode at the sink, not the source.** SQL → parameterized queries (never string concat). HTML → context-aware escaping (HTML body vs attribute vs JS vs URL — they differ). Shell → `subprocess` with a list, never `shell=True`. JSON → use the library, never hand-roll.
- **Secrets.** Never in code, logs, error messages, or URL paths. Read from env, secret manager, or sealed config. Redact from any structure you log. Rotate on exposure.
- **Auth invariants.** Verify *every* request. Authorize on the server. Never trust client-supplied identity claims (`user_id` in a POST body) without a server-side check.
- **Crypto.** Use the platform's high-level primitives (`secrets.token_urlsafe`, `bcrypt`/`argon2`, libsodium). Do not invent or hand-roll cryptographic operations. Never use `MD5`/`SHA1` for security. Never use `random` (use `secrets`).
- **Defaults that are safe.** Deny by default; opt in to share. HTTPS only. `SameSite=Lax` minimum. CSRF tokens on state-changing forms.

References: OWASP Top 10 (current), CWE Top 25, RFC 7519 (JWT), RFC 6749 (OAuth 2.0).
