# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-05-28

The big-SDK release. v0.2 was a focused `reason()`/`generate()` primitive;
v0.3 turns it into a full toolkit for AI-assisted coding — six providers,
async, streaming, batching, conversations, workflows, a CLI, custom skills,
and 16 new bundled skills. 100% backwards-compatible at the public API
surface; existing v0.2 code keeps working.

### Added — providers
- **OpenAI** (`provider="openai"`) — direct, no OpenRouter hop. Reads `OPENAI_API_KEY`.
- **Gemini** (`provider="gemini"`) — Google Gemini direct via REST. Reads `GEMINI_API_KEY` or `GOOGLE_API_KEY`.
- **Ollama** (`provider="ollama"`) — local OSS models. No key required. Reads `OLLAMA_BASE_URL` (default `http://localhost:11434`).
- **Stub** (`provider="stub"`, also `StubProvider` / `AsyncStubProvider`) — in-memory scripted responses for users' own tests. Re-exported under `essarion_build.testing`.
- `register_provider(name, factory)` / `unregister_provider(name)` for user-defined providers.
- `list_providers()` enumerates built-in plus custom providers.

### Added — async API
- `areason()` / `agenerate()` mirror the sync entrypoints; awaitable.
- `AsyncLiteRuntime`, `AsyncProvider` protocol, `AsyncRuntime` protocol.
- Async transports for every built-in provider.
- `select_async_runtime()`, `build_async_provider()`, `register_async_provider()`, `unregister_async_provider()`.

### Added — streaming
- `stream_reason()` / `stream_generate()` yield `ReasoningEvent` objects: `phase_start`, `token`, `phase_end`, `usage`, `complete`.
- `StreamingProvider` protocol; the Anthropic provider implements native token streaming via the SDK's `messages.stream`. Buffered providers emit one `token` event per phase, so the UI shape is identical either way.
- `StreamChunk` carries the partial text and (on the final chunk) the usage for the call.

### Added — multi-turn
- `Conversation` class with persistent `Context`, ordered `history` of `ConversationTurn`, `usage` aggregation, and `fork()` for branching.
- Each turn's plan + verdict is auto-summarized into the context's `notes` so subsequent turns can refer back without restating.

### Added — high-level workflows
- `essarion_build.workflows.review()` / `fix_bug()` / `write_tests()` / `refactor()` / `docs()`.
- Each workflow auto-picks a sensible default skill set, frames the task, and runs the loop.
- Accept `context=`, `repo=`, `diff=` kwargs plus any `reason()`/`generate()` kwargs.

### Added — batching
- `batch_reason()` / `batch_generate()` run many `areason()` / `agenerate()` calls concurrently with a configurable `max_concurrency` semaphore.
- `BatchResult` exposes `.ok` and `.errors`. One task's failure doesn't fail the rest.
- `run_batch(coro)` helper to call a batch from sync code.

### Added — Context upgrades
- `add_repo()` now accepts `include=` / `exclude=` (gitignore-style globs) and `max_files=`.
- `add_file(path)` for loading a single focused file.
- `with_custom_skill(name, body)` injects a project-specific skill.
- `with_skills_dir(path)` loads every `*.md` under a directory as a custom skill.
- `add_diff(body, title=...)` attaches a focused diff (rendered as `<diffs>` in the prompt block).
- `add_note(text)` pins a one-sentence reminder (rendered as `<notes>`).
- `total_chars()` and `estimate_tokens()` for pre-flight budgeting.
- New `Diff` model class.

### Added — response cache
- `ResponseCache(root)` — on-disk, content-addressed (SHA-256 of provider, model, system, messages, max_tokens).
- `CachingProvider(inner, cache, provider_name=...)` wraps any provider; identical calls are served from disk.
- Cache exposes `.hits`, `.misses`, `.clear()`.

### Added — CLI
- `essarion-build` console entry point.
- Subcommands: `skills`, `providers`, `version`, `estimate`, `reason`, `generate`.
- Flags: `--repo`, `--doc`, `--skill`, `--no-skills`, `--diff`, `--provider`, `--model`, `--max-tokens`, `--json`, `--stream`.
- Reads tasks from stdin when the positional argument is `-`.

### Added — validators
- `essarion_build.validators` module: cheap, deterministic post-generation checks (no model calls).
- `validate_python()` flags syntax errors, bare `except`, `eval`/`exec`, mutable defaults, TODO/FIXME markers.
- `validate_json()` enforces RFC 8259.
- `validate_unified_diff()` sanity-checks unified diff headers.
- `register_validator(kind, fn)` for user-defined checks. `list_validators()` enumerates.

### Added — skills (+16)
- `rust_idioms`, `go_idioms`, `sql_idioms`
- `react_patterns`, `state_management`
- `accessibility`, `internationalization`
- `caching`, `microservices`, `event_driven`
- `feature_flags`, `migrations`, `release_engineering`, `incident_response`
- `llm_integration`, `dx`

### Added — testing helpers
- `essarion_build.testing` re-exports `StubProvider`, `AsyncStubProvider`, plus `run_with_stub()` and `arun_with_stub()` convenience helpers.

### Added — runtime exposure
- `LiteRuntime`, `AsyncLiteRuntime`, `Runtime`, `AsyncRuntime`, `select_runtime`, `select_async_runtime`, `build_provider`, `build_async_provider` are now re-exported from the package root.

### Changed
- Default classifier bumped to `Development Status :: 4 - Beta`.
- README rewritten end to end. Architecture diagram up top; provider table covers all six; workflows / streaming / async / batching / conversation / cache / CLI / validators all documented with runnable examples.
- `pyproject.toml` adds `[project.scripts]` for the `essarion-build` CLI, adds `pytest-asyncio` to the test extras, sets `asyncio_mode = "auto"`.

### Tests
- Suite grew from 42 to 121 cases. New files: `test_async_api.py`, `test_streaming.py`, `test_context_extras.py`, `test_conversation.py`, `test_cache.py`, `test_workflows.py`, `test_cli.py`, `test_validators.py`, `test_batch.py`.

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

[Unreleased]: https://github.com/hapi-developer/essarion_build/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/hapi-developer/essarion_build/releases/tag/v0.3.0
[0.2.0]: https://github.com/hapi-developer/essarion_build/releases/tag/v0.2.0
