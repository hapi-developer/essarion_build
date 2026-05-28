# Architecture

A two-page tour of how `essarion_build` is organized internally. Read
this if you want to add a new provider, swap a runtime, or understand
why something is shaped the way it is.

## The seam

Three nouns:

```
Context  ──→  Runtime  ──→  Provider
 (input)      (loop)        (model)
```

- `Context` is the data you bring: skills, repo files, docs, diffs,
  notes, custom skills. It renders to an XML-ish block.
- `Runtime` is the multi-step loop: `plan → (draft) → selfcheck`. It
  calls the Provider 2–3 times per `reason()`/`generate()` invocation.
- `Provider` is the thin chat-completion seam: text in, text out, with
  retries and typed error mapping.

Each interface is small. New providers add one class; new runtimes add
one class; new context kinds add one Pydantic model + one branch in
`to_prompt_block()`.

## Where everything lives

```
src/essarion_build/
├── __init__.py            re-exports the public surface
├── _config.py             module-level defaults (provider, model, budget)
├── _context.py            Context, RepoFile, Doc, Diff, etc.
├── _prompts.py            system + per-phase instruction prompts
├── _providers.py          sync Provider seam + 6 implementations
├── _async_providers.py    async siblings of the above
├── _runtime.py            sync Runtime protocol + LiteRuntime + CloudRuntime
├── _async_runtime.py      async siblings of the above
├── _reasoning.py          Reasoning + reason()
├── _generate.py           Generation + generate()
├── _async_api.py          areason() / agenerate()
├── _streaming.py          stream_reason() / stream_generate()
├── _batch.py              batch_reason() / batch_generate()
├── _conversation.py       Conversation (multi-turn)
├── _cache.py              ResponseCache, CachingProvider
├── _compaction.py         compact() / truncate_files() / keep_only_files()
├── _telemetry.py          configure_telemetry() + emit()
├── _skills.py             bundled skills loader
├── _decorators.py         @reasoned registry
├── workflows.py           review() / fix_bug() / write_tests() / …
├── tools.py               register_tool() / run_tools_in_plan()
├── validators.py          validate_python() / validate_json() / …
├── evals.py               EvalCase / run_eval() / scorers
├── auth.py                from_env() + Platform API stub
├── testing.py             StubProvider re-exports + helpers
├── pytest_plugin.py       fixtures for users' own tests
├── cli.py                 essarion-build CLI
├── exceptions.py          EssarionError hierarchy
└── skills/                42 bundled skill markdown files
```

## The reasoning loop

`reason()` runs 2 calls:

```
1. plan ─────────► <plan>, <tradeoffs>, <verdict (preliminary)>
2. selfcheck ───► <verdict (refined)>
```

`generate()` runs 3 calls:

```
1. plan ─────────► <plan>, <tradeoffs>, <verdict (preliminary)>
2. draft ────────► <code>
3. selfcheck ───► <verdict (refined)>, <defense>
```

Each call passes the **same system prompt** (frozen — cache-friendly) plus
the running message history. The system prompt prefix is:

```
<system prompt>

<context>
  <skills>...</skills>
  <notes>...</notes>
  <diffs>...</diffs>
  <repo>...</repo>
  <docs>...</docs>
  <sources>...</sources>
  <agent_skills>...</agent_skills>
</context>
```

This shape is stable across the 2–3 calls in a single loop, which lets
prompt caching (Anthropic, Gemini) and a content-hash cache
(`ResponseCache`) do their work.

## Tag repair

Small models drop tags. After each call:

```
if any required tag is missing:
    ask one follow-up: "Re-emit ONLY the missing tag(s) in <tag>…</tag>"
    merge the result into the tags from the first call
```

If the repair pass also fails, we raise `ReasoningFormatError` rather
than returning an empty `defense` field. The runtime tracks usage from
the repair call separately so the reported total is honest.

## Errors

Every error rooted at `EssarionError`. Provider transport raises typed
subclasses of `ProviderError`:

- `ProviderAuthError` (HTTP 401/403)
- `ProviderRateLimitError` (HTTP 429 after retries)
- `ProviderHTTPError` (everything else after retries)
- `ProviderResponseError` (2xx but unparseable)

The runtime raises:

- `ReasoningFormatError` (tags still missing after repair)
- `CloudRuntimeNotAvailable` (the future Cloud runtime is requested)

`Context` raises `ContextError` for programmer errors (missing path,
unknown skill).

## Adding a provider

1. Implement a class with `model: str` attribute and `complete()` method
   matching the `Provider` protocol in `_providers.py`.
2. Add a branch in `build_provider()`.
3. (Optional but recommended) Implement the async sibling in
   `_async_providers.py` and add it to `build_async_provider()`.
4. (Optional) Implement `stream()` for `StreamingProvider` if your
   transport supports token streaming.

Or, for one-off users, call `register_provider("name", factory)`. No code
changes needed.

## Adding a runtime

A `Runtime` has two methods: `reason()` and `generate()`, both returning
a `RuntimeResult` (just a dict with `plan`, `tradeoffs`, `verdict`,
optional `code`/`defense`, and `usage`). Implement them however you
like — call multiple models, use tool use, do something exotic. Wire it
into `select_runtime()`.

The current shipping runtimes:

- `LiteRuntime` — the 3-step local loop
- `CloudRuntime` — stub (raises `CloudRuntimeNotAvailable`)

## Adding a workflow

Workflows are 10-line wrappers around `reason()` / `generate()`. They
pick a sensible skill set, reframe the task, and run the loop. Add new
ones to `workflows.py` and re-export them from `__all__`.

## Adding a skill

Drop a markdown file under `src/essarion_build/skills/`. Add the name to
the `EXPECTED_SKILLS` set in `tests/test_smoke.py`. That's it — the
loader discovers it automatically.

A skill is a short brief: 10–15 bullet points, each one actionable.
Bias toward what *not* to do; the model has read every Python tutorial
already, but "don't `import db_singleton` in a function that takes the
DB" is the kind of guidance it benefits from in context.
