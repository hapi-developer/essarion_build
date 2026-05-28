# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-05-28

### Added
- Tag-repair pass: if a required `<plan>`/`<tradeoffs>`/`<verdict>`/`<code>`/`<defense>` tag is missing from a model response, the runtime asks once for just the missing tag(s) before raising.
- Typed provider exceptions: `ProviderAuthError` (HTTP 401/403), `ProviderRateLimitError` (HTTP 429), `ProviderHTTPError` (other non-2xx and network failures), `ProviderResponseError` (unparseable 2xx), and `ReasoningFormatError` (required tags still missing after the repair pass).
- Usage tracking: `Reasoning` and `Generation` carry a `Usage(prompt_tokens, completion_tokens, total_tokens, cached_tokens)` field aggregated across every provider call in the loop, including any repair retries.
- Per-call `max_tokens` kwarg on `reason()` and `generate()` (was previously global-only via `configure()`).
- Exponential-backoff retry (up to 2 retries) on HTTP 429, 5xx, and connection errors before surfacing the typed exception.

### Fixed
- `_OpenRouterProvider` no longer leaks `httpx.Client` instances — the client is now created per-call inside a context manager.

### Changed
- README rewritten to document usage tracking, per-call `max_tokens`, tag-repair behavior, and the typed-exception table.
- **Breaking:** `Provider.complete()` now returns `ProviderResponse(text, usage)` instead of `str`. Only affects users who wrote a custom `Provider`.

### Tests
- Suite grew from 26 to 42 cases. Added coverage for tag repair (happy path, failed repair, no-repair-needed), usage arithmetic and aggregation, per-call `max_tokens` override, and HTTP error mapping / retry behavior via `httpx.MockTransport`.

[Unreleased]: https://github.com/hapi-developer/essarion_build/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/hapi-developer/essarion_build/releases/tag/v0.2.0
