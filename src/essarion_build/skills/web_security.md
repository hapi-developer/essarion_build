# Web security

A focused complement to `secure_coding`. Covers browser-side and HTTP-specific attack classes.

- **CSP (Content Security Policy) on every response.** `default-src 'self'; script-src 'self' 'nonce-...'`. Blocks most XSS even when an injection slips through. Start in `report-only` mode if you must, then enforce.
- **Cookies: `HttpOnly`, `Secure`, `SameSite`.** `HttpOnly` blocks JS access (XSS cookie theft); `Secure` mandates HTTPS; `SameSite=Lax` (default) mitigates CSRF on most state changes. `SameSite=Strict` for the auth cookie itself.
- **CSRF tokens on every state-changing form.** SameSite=Lax isn't enough for fetches from other origins (e.g. subdomain takeover). Token tied to session, rotated, checked server-side.
- **CORS is permissive by default; lock it down.** `Access-Control-Allow-Origin: https://yourdomain.com`, not `*`. Never combine `*` with `Allow-Credentials: true` — many browsers reject this; the spec forbids it for good reason.
- **HSTS with preload.** `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`. Once preloaded, the browser refuses to ever speak HTTP to your domain. One-way commitment — make sure HTTPS works everywhere first.
- **`X-Content-Type-Options: nosniff`.** Stops MIME-type sniffing, which can turn a "harmless" file upload into executable script. Free, no downside.
- **`X-Frame-Options: DENY` (or CSP `frame-ancestors`).** Clickjacking defense. Unless you have a real reason to allow iframing, deny it.
- **Subresource Integrity for third-party scripts.** `<script src="..." integrity="sha384-..." crossorigin="anonymous">`. If the CDN serves a different file, the browser refuses to run it. Catches supply-chain compromise.
- **Avoid `dangerouslySetInnerHTML` / `v-html` / equivalents.** When you must, sanitize via a real library (DOMPurify), not a regex. Sanitization is hard; rolling your own is how XSS happens.
- **JWT pitfalls.** Never trust `alg=none`. Never let the client choose the algorithm. Verify the signature *before* reading any claims. Short-lived; refresh via a server endpoint; revocation list for compromised sessions.
- **Same-origin SSE/WebSocket.** Authenticate before upgrading. CORS doesn't apply to WebSockets in many browsers; check the `Origin` header in your handshake.
- **File uploads: type-check, size-cap, virus-scan, store off-domain.** Serving user uploads from your main domain is XSS-via-SVG waiting to happen. Use a separate, sandboxed domain.
- **Open redirect bugs are real.** `?next=/dashboard` looks innocent; `?next=https://evil.com` isn't. Validate redirect targets against an allow-list.
- **Server-Side Request Forgery (SSRF) when accepting URLs.** Block private IP ranges (RFC 1918, link-local, metadata IPs like 169.254.169.254). Use a separate egress proxy if you really must let users pass URLs.
