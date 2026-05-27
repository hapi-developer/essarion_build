# Auth and security

- **Authentication ≠ authorization.** AuthN: who are you? AuthZ: what may you do? Mixing them in one check is how privilege escalation slips through.
- **Password hashing: `argon2id` (preferred) or `bcrypt`.** Never plain hashes, never custom KDFs, never reuse the same hash function as session-token derivation.
- **Sessions vs tokens.** Server-side sessions with an opaque cookie are simpler and revocable. JWTs are stateless but tricky — see below. If you don't need cross-domain stateless auth, use sessions.
- **JWT pitfalls (RFC 7519).** Verify `alg` against an allow-list (reject `none`, reject algorithm-swap attacks). Verify `iss`, `aud`, `exp` on every request. Short lifetimes (minutes); use refresh tokens for the long-lived path. Never put secrets in the payload — it's base64, not encrypted.
- **OAuth 2.0 / OIDC (RFC 6749, OIDC core).** Use a library; don't hand-roll the flow. PKCE for public clients. `state` and `nonce` for CSRF. Validate `id_token` signatures.
- **Cookies.** `Secure`, `HttpOnly`, `SameSite=Lax` (or `Strict`). Cookie auth requires CSRF tokens on state-changing requests.
- **CSRF.** Use the framework's protection. Same-origin POSTs from your own forms should include a token bound to the session.
- **CORS is not security.** It controls which origins *the browser* allows; the server still gets the request. Never use CORS as a substitute for authentication.
- **Rate-limit auth endpoints aggressively.** Login, password reset, MFA verify. Lockout after N failures; alert.
- **Audit log all auth events.** Logins, logouts, permission changes, MFA enrollments, resets. With `request_id` and IP. Append-only.
- **Don't roll your own MFA.** TOTP via a vetted library; passkeys/WebAuthn for the modern path.
