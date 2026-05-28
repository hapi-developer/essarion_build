# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] - 2026-05-28

The "essarion CLI coding agent" release. v0.3 made `essarion-build` a
serious SDK; v0.4 turns it into a fully-featured CLI coding agent
without losing any of the SDK surface. Everything is `pip install
essarion-build`.

### Added — `essarion` CLI coding agent

A new module, `essarion_build.agent`, ships an interactive coding agent
on top of the SDK. Bare `essarion` launches the REPL; `essarion
<subcmd>` falls through to the existing CLI subcommands.

Differentiators vs Claude Code / Codex / Aider / Cursor:

- **Plan-first interactivity.** The SDK's `reason()` runs first; the
  user sees the plan in a panel and can approve / edit / cancel
  *before* any code-generation call is paid for.
- **Live token-budget meter.** Per-session USD budget; live cost
  readout in the footer; per-turn cost line. Makes the
  amplification-savings story visible.
- **Smart skill selection.** A tiny keyword-based picker chooses 3-5
  relevant skills out of 54 instead of loading them all. Big context
  savings.
- **Multi-model arbitrage.** `--escalate <bigger-model>` makes the
  agent retry with a stronger model only when the cheap-model
  selfcheck rejects the draft.
- **Reasoning-trace persistence.** Sessions saved to
  `~/.essarion/sessions/{id}.json`. Replay with `essarion --resume <id>`.
- **Workflow-prefixed shortcuts.** `review: src/auth.py`,
  `fix-bug: payment hangs`, `tests: parse_jwt`, `refactor: …`, `docs:
  …`, `security-review: …`, `perf-review: …`, `pr-description: …`,
  `explain: …` route to the matching `workflows.*` function.

Visual polish via `rich`: panels, syntax-highlighted code, live status
spinners, color-coded phase headers (plan = magenta, draft = cyan,
selfcheck = yellow), persistent footer with model + budget + token +
turn counts.

Slash commands inside the REPL: `/help`, `/quit`, `/clear`,
`/budget [N]`, `/model <p>/<m>`, `/escalate <m>`, `/skills
[auto|all|none]`, `/cd <path>`, `/pwd`, `/history`, `/save`, `/load`,
`/export`, `/yolo`, `/version`.

CLI flags: `--task`, `--cwd`, `--budget`, `--provider`, `--model`,
`--escalate`, `--skills {auto,all,none}`, `--resume <id>`,
`--max-tokens`.

### Added — agent sub-modules

- `essarion_build.agent._loop` — the plan-first turn loop (uses
  `reason()` + `generate()` + `workflows.*` from the SDK)
- `essarion_build.agent._session` — Session state, TaskTurn,
  `estimate_cost_usd()`, persistence to `~/.essarion/sessions/`
- `essarion_build.agent._skill_picker` — keyword-based skill selection
- `essarion_build.agent._tools` — sandboxed file/grep/shell tools
  (read_file, list_dir, grep, write_file, apply_diff, run_shell)
- `essarion_build.agent._ui` — rich-based panels, prompts, footer
- `essarion_build.agent._commands` — slash-command dispatcher
- `essarion_build.agent._theme` — color theme + ASCII banner
- `essarion_build.agent.main` — entry point + top-level dispatcher

### Added — `essarion` console script

A new entry point in `pyproject.toml`: `essarion =
essarion_build.agent.main:main_or_subcommand`. Bare `essarion` runs
the agent REPL; `essarion <subcmd>` (skills / providers / workflows /
version / estimate / reason / generate) passes through to the existing
`essarion-build` CLI.

The `essarion-build` console script is preserved unchanged.

### Added — dependencies
- `rich>=13.7` (TUI, syntax highlighting, panels, progress)

### Tests
- Suite grew from 229 to 284 cases. New files: `test_agent_skill_picker.py`,
  `test_agent_tools.py`, `test_agent_session.py`, `test_agent_loop.py`,
  `test_agent_commands.py`, `test_agent_main.py`.

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

### Added — structured output
- `generate_json(task, schema=...)` / `agenerate_json(...)` — generate a JSON object that validates against a Pydantic model or a raw JSON schema dict. One automatic repair pass on validation failure. `SchemaValidationError` if even the repair pass fails.
- Re-exported `SchemaValidationError` from the package root.

### Added — evaluation harness
- `essarion_build.evals.EvalCase`, `Score`, `CaseResult`, `Report`.
- `run_eval(cases, runner, scorer)` runs every case, scores, aggregates token usage.
- Built-in scorers: `exact_match`, `contains_all`, `keyword_overlap`.
- `Report.delta(baseline)` returns regressed/improved lists for CI gates.
- Re-exported as `essarion_build.evals`.

### Added — context compaction
- `compact(ctx, max_tokens=N)` trims repo files then docs until the context fits.
- `truncate_files(ctx, max_chars_per_file=N)` caps individual file bodies with a `(truncated)` marker.
- `keep_only_files(ctx, patterns=[...])` filters repo files by fnmatch glob.
- All return a new Context — the input is untouched.
- `Context.merge(other)` unions every section; repo files de-dup by path with newest-wins.

### Added — telemetry
- `configure_telemetry(on_event=, enabled=)` wires a user callback for SDK events.
- Events: `loop_start`, `phase_call`, `phase_done`, `tag_repair_attempt`, `tag_repair_failed`, `loop_done`.
- Buggy user callbacks are swallowed so they can never break the loop.

### Added — prompt overrides
- `configure_prompts(system=, plan=, draft=, selfcheck_reason=, selfcheck_generate=)` for teams that want their own house voice.
- `reset_prompts()` restores defaults.

### Added — tools (model-side)
- `register_tool(name, description=)` decorator.
- `run_tools_in_plan(text, allow=)` evaluates `<tool_call>` tags in arbitrary text, replacing them with `<tool_result>` (or `<tool_result error="true">`).
- `tool_manifest()` prints a one-line summary for injection into Context.
- Provider-agnostic by design — works on every backend.

### Added — pytest plugin
- `essarion_build.pytest_plugin` provides fixtures: `essarion_stub`, `essarion_async_stub`, `essarion_runtime`, `essarion_async_runtime`, `essarion_context`, `essarion_skills`, `isolated_prompts`, `isolated_telemetry`, `isolated_providers`.

### Added — auth
- `essarion_build.auth.from_env(*providers)` reads provider env vars and returns a `Credential` for `configure()`.
- `from_platform_api(token)` still NotImplementedError, but now rejects empty/whitespace tokens with ValueError so typos are distinguishable from "not shipped yet".

### Added — workflows (+4)
- `security_review()` — threat-model-shaped review with CWE/OWASP refs.
- `performance_review()` — hot-path analysis with expected-payoff estimates.
- `write_pr_description()` — generates a PR body (summary, why, what, test plan, risk).
- `explain_code()` — 3-layer explanation (1 sentence / 5 sentences / full walkthrough).

### Added — skills (+21 total, 42 in v0.3)
- `rust_idioms`, `go_idioms`, `sql_idioms`
- `react_patterns`, `state_management`
- `accessibility`, `internationalization`
- `caching`, `microservices`, `event_driven`
- `feature_flags`, `migrations`, `release_engineering`, `incident_response`
- `llm_integration`, `dx`
- `dependency_injection`, `cloud_infra`, `kubernetes`, `code_style`, `code_smells`

### Added — CLI subcommands
- `essarion-build workflows` lists bundled workflows with their docstrings.

### Added — docs and examples
- `examples/` — 8 runnable scripts (quick start, workflows, streaming, async batch, conversation, telemetry, custom provider, cache).
- `docs/COOKBOOK.md` — 20 runnable recipes covering every public surface.
- `docs/ARCHITECTURE.md` — two-page internal-structure tour.

### Added — CI
- `.github/workflows/ci.yml` matrix over 3.11/3.12/3.13 + CLI smoke job + build+twine check.

### Tests
- Suite grew from 42 to 192 cases. New files: `test_async_api.py`, `test_streaming.py`, `test_context_extras.py`, `test_conversation.py`, `test_cache.py`, `test_workflows.py`, `test_cli.py`, `test_validators.py`, `test_batch.py`, `test_telemetry.py`, `test_prompts.py`, `test_tools.py`, `test_pytest_plugin.py`, `test_auth.py`, `test_evals.py`, `test_compaction.py`, `test_schemas.py`.

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

[Unreleased]: https://github.com/hapi-developer/essarion_build/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/hapi-developer/essarion_build/releases/tag/v0.4.0
[0.3.0]: https://github.com/hapi-developer/essarion_build/releases/tag/v0.3.0
[0.2.0]: https://github.com/hapi-developer/essarion_build/releases/tag/v0.2.0
