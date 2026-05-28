# essarion-build

A **BYOK reasoning amplification SDK** for AI-assisted coding. Bring your own model provider; `essarion_build` provides the reasoning loop, the grounding context, the bundled software-development skills, and the structured outputs.

`essarion_build` is not a wrapper for any single LLM. It is a deliberate **plan → draft → self-check** pipeline that turns *whatever model you wire in* into a more thoughtful coder. The default is tuned to amplify **cheap** models — making a small, fast GPT reason about coding the way a senior engineer would.

```text
                ┌──────────────────────────────────────────┐
                │      essarion-build SDK (this repo)      │
                │                                          │
   your task ─► │  ┌──────────┐  ┌──────────┐  ┌────────┐  │ ─► structured
                │  │   plan   │ →│  draft   │ →│selfcheck│ │    output
                │  └──────────┘  └──────────┘  └────────┘  │   (plan, code,
                │  + bundled skills + repo + docs + diffs  │    defense, …)
                │                                          │
                └──────────────────────────────────────────┘
                                  ▲
                       any LLM provider (BYOK)
                  OpenRouter · Anthropic · OpenAI · Gemini
                       Ollama (local) · custom
```

## Install

```bash
pip install essarion-build
```

Set your provider key. The default is OpenRouter, which gives you access to ~any model through one API:

```bash
export OPENROUTER_API_KEY=sk-or-...
```

Or pick another:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
export GEMINI_API_KEY=...
# Ollama needs no key; runs locally
```

## Quick start

```python
from essarion_build import Context, reason, generate

ctx = (
    Context()
      .with_all_skills()                 # 42 bundled coding-practice skills
      .add_repo("./")                    # ground in your codebase
      .add_docs("https://datatracker.ietf.org/doc/html/rfc7519")
)

# Pure reasoning — returns a plan, no code yet
r = reason("harden JWT signature check", context=ctx)
print(r.plan)                  # the numbered reasoning trace
print(r.tradeoffs)             # what was considered and rejected
print(r.verdict)               # "ship" or "do not ship without X"
print(r.usage.total_tokens)    # token cost across the whole loop

# Reason + produce code — returns reasoning AND a snippet
g = generate("harden JWT signature check", context=ctx)
print(g.code)                  # the proposed change
print(g.reasoning)             # the underlying Reasoning object
print(g.defense)               # one-paragraph "why this is safe to ship"
print(g.usage.total_tokens)    # token cost across plan + draft + selfcheck
```

## Bundled software-dev skills

A core idea: cheap models cost less but reason worse. `essarion_build` closes the gap by **injecting senior-engineer skills into the context** — short, focused markdown briefs the model reads alongside the task.

```python
from essarion_build import Context, list_skills, load_skill

list_skills()
# [
#   'accessibility', 'api_design', 'auth_security', 'caching', 'cli_design',
#   'cloud_infra', 'code_review', 'code_smells', 'code_style', 'concurrency',
#   'data_modeling', 'database_design', 'debugging', 'dependency_injection',
#   'dependency_management', 'documentation', 'dx', 'error_handling',
#   'event_driven', 'feature_flags', 'git_workflow', 'go_idioms',
#   'incident_response', 'internationalization', 'kubernetes',
#   'llm_integration', 'logging', 'microservices', 'migrations',
#   'observability', 'performance', 'python_idioms', 'react_patterns',
#   'refactoring', 'release_engineering', 'rust_idioms', 'scope_discipline',
#   'secure_coding', 'sql_idioms', 'state_management', 'testing',
#   'typescript_idioms'
# ]

# Pick the ones relevant to your task...
ctx = Context().with_skills(["secure_coding", "auth_security", "error_handling"])

# ...or load them all (recommended default for coding tasks)
ctx = Context().with_all_skills()

# Or read one inline
print(load_skill("secure_coding"))
```

Each skill is a short, actionable brief. `secure_coding` covers input validation, output encoding, secret handling, and crypto defaults. `scope_discipline` covers staying within scope. `testing` covers what to test and how. The full set is bundled with the package; no network calls.

### Custom skills

Need project-specific guidance? Inject your own:

```python
ctx = (
    Context()
      .with_all_skills()
      .with_custom_skill("house_style", open("./docs/style.md").read())
      .with_skills_dir("./team_skills")    # every *.md file in the dir
)
```

## High-level workflows

For the common cases, skip the prompt engineering — call a workflow.

```python
from essarion_build import workflows, Context

# Review a target with the review-default skill set
r = workflows.review("src/auth.py", repo="./")

# Fix a bug end-to-end (plan → patch → defense)
g = workflows.fix_bug("payment endpoint hangs on null email", repo="./")

# Generate tests for a public surface
g = workflows.write_tests("class JWTValidator", repo="./")

# Refactor with behavior-preserving guarantees
g = workflows.refactor("UserService.god_method", repo="./")

# Write docs in the existing house style
g = workflows.docs("public Context API", repo="./")
```

Each workflow picks a sensible default skill set, frames the task, and runs the loop. They're thin on purpose — drop down to `reason()` / `generate()` when you need full control.

## Streaming

See progress in real time. Yields a `phase_start`/`token`/`phase_end`/`usage`/`complete` event sequence:

```python
from essarion_build import stream_generate, Context

for event in stream_generate("write a JWT validator", context=Context().with_all_skills()):
    if event.kind == "token":
        print(event.text, end="", flush=True)
    elif event.kind == "phase_end":
        print(f"\n--- {event.phase} done ---")
    elif event.kind == "complete":
        print(f"\nFinal usage: {event.usage}")
```

Providers with native token streams (Anthropic) emit fine-grained tokens; buffered providers emit one chunk per phase. The UI surface is the same either way.

## Async API

`areason()` / `agenerate()` mirror the sync API:

```python
import asyncio
from essarion_build import Context, agenerate

async def main():
    g = await agenerate("write a JWT validator", context=Context().with_all_skills())
    print(g.code)

asyncio.run(main())
```

### Parallel batches

For independent tasks, run them concurrently:

```python
from essarion_build import batch_generate, run_batch, Context

tasks = [
    "review src/auth.py",
    "review src/billing.py",
    "review src/notifications.py",
]
results = run_batch(batch_generate(tasks, context=Context().with_all_skills(),
                                   max_concurrency=4))
print(f"{len(results.ok)} succeeded, {len(results.errors)} failed")
```

One task's failure doesn't fail the rest — failures are returned as `Exception` instances in the result list.

## Multi-turn conversations

When tasks build on each other, use `Conversation`. Each turn's plan + verdict is auto-summarized into the context so the next call can refer back:

```python
from essarion_build import Conversation, Context

conv = Conversation(context=Context().with_all_skills().add_repo("./"))

# Turn 1: agree on the schema
r1 = conv.reason("design a users-and-orgs schema with row-level multitenancy")

# Turn 2: write the migration — the prior plan + verdict are in the context
g2 = conv.generate("write the SQL migration for the schema above")

# Turn 3: tests — same context, plus turns 1+2
g3 = conv.generate("write integration tests for the migration")

print(conv.usage.total_tokens)   # aggregated across all 3 turns
print(len(conv.history))         # 3
forked = conv.fork()              # branch for what-if scenarios
```

## Diff-focused context

Reviewing a change? Don't load the whole repo; load the diff:

```python
import subprocess
from essarion_build import workflows, Context

diff = subprocess.check_output(["git", "diff", "main"]).decode()

ctx = Context().with_all_skills().add_diff(diff, title="main..HEAD")
r = workflows.review("the change above", context=ctx)
```

## Token budgeting and usage tracking

Every `reason()` and `generate()` result carries a `usage` field with prompt, completion, total, and provider-reported cached token counts:

```python
r = reason("...", context=ctx)
print(r.usage)
# Usage(prompt_tokens=2618, completion_tokens=373, total_tokens=2991, cached_tokens=0)
```

Cap the per-call budget without changing the module default:

```python
g = generate("...", context=ctx, max_tokens=1500)
```

Pre-flight estimate before sending:

```python
print(ctx.estimate_tokens())     # ~1.2k? send it. ~120k? trim.
print(ctx.total_chars())         # raw character count
```

Or set the budget globally:

```python
import essarion_build
essarion_build.configure(max_tokens=2000)
```

The runtime divides the budget across the 2 calls (`reason`) or 3 calls (`generate`) in the loop, plus any one-shot tag-repair retries (see below). Usage from those retries is included in the total.

## Response cache

For dev iteration, skip duplicate provider calls:

```python
from essarion_build import LiteRuntime, ResponseCache, CachingProvider, build_provider

provider = build_provider(name="anthropic", api_key=None, model="claude-sonnet-4-6")
cache = ResponseCache("./.essarion-cache")
cached_provider = CachingProvider(provider, cache, provider_name="anthropic")

# Use it as you would any provider:
rt = LiteRuntime(cached_provider)
```

Identical `(system, messages, max_tokens)` tuples are served from disk; cache misses populate it.

## Post-generation validators

Cheap, deterministic checks on generated code (no model calls):

```python
from essarion_build.validators import validate

g = generate("write a Python function …", context=ctx)
issues = validate(g.code, kind="python")
for i in issues:
    print(f"{i.severity}: {i.message} (line {i.line})")
```

Built-in validators: `python` (syntax, bare except, mutable defaults, dangerous calls, TODO markers), `json` (RFC 8259 strictness), `diff` (unified-diff header check). Register your own with `register_validator(kind, fn)`.

## Cheap-model survival kit

Small models drop XML tags. When the model returns a selfcheck without the `<defense>` tag, the runtime asks once for just the missing tag(s) and merges the result. If even the repair pass fails, you get a typed `ReasoningFormatError` — not a silently empty `defense` field.

You don't have to opt in; this happens automatically inside `LiteRuntime`.

## The `@reasoned` decorator

Mark functions you want the `essarion-build` CLI to enumerate. In normal Python execution the original body runs unchanged — the decorator just records the function in a module-level registry.

```python
from essarion_build import reasoned

@reasoned(context=ctx)
def parse_jwt(token: str) -> Claims:
    """Parse a JWT and return validated claims."""
    ...  # body is yours; the CLI uses this entry for future reason+generate runs
```

## BYOK and providers

The Provider seam keeps `essarion_build` model-agnostic. v0.3 ships six concrete providers; the model you run is your choice:

| Provider | Env var | Default model | Notes |
|---|---|---|---|
| `openrouter` (default) | `OPENROUTER_API_KEY` | `openai/gpt-4o-mini` | Routes to ~any model behind one OpenAI-compatible API. The cheap-default story. |
| `anthropic` | `ANTHROPIC_API_KEY` | (provide one, e.g. `claude-sonnet-4-6`) | Direct to the Claude API. Uses prompt caching on the system block. Streaming supported. |
| `openai` | `OPENAI_API_KEY` | (provide one, e.g. `gpt-4o-mini`) | Direct to OpenAI. |
| `gemini` | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | (provide one, e.g. `gemini-2.0-flash`) | Direct to Google Gemini. |
| `ollama` | (none) | (provide one, e.g. `llama3.2`) | Local OSS models. Set `OLLAMA_BASE_URL` if not on `localhost:11434`. |
| `stub` | (none) | n/a | In-memory scripted responses for tests. |

Switch globally or per-call:

```python
import essarion_build

# Stay on OpenRouter but use a stronger model
essarion_build.configure(model="anthropic/claude-sonnet-4.6")  # OpenRouter slug

# Or switch provider entirely
essarion_build.configure(provider="anthropic", model="claude-sonnet-4-6")

# Per-call override
generate("...", provider="openai", model="gpt-4o-mini", max_tokens=1500)
```

### Register a custom provider

```python
from essarion_build import register_provider

class _MyProvider:
    def __init__(self, *, api_key=None, model: str) -> None:
        self.model = model
    def complete(self, *, system, messages, max_tokens):
        ...  # return ProviderResponse(text=..., usage=Usage(...))

register_provider("my-llm", lambda *, api_key, model: _MyProvider(api_key=api_key, model=model))

# Now usable just like a built-in:
generate("...", provider="my-llm", model="my-model-v1")
```

Async siblings (`register_async_provider`, `build_async_provider`, `AsyncProvider` protocol) follow the same shape.

## Structured output (JSON-schema mode)

When you want a typed payload instead of free text, use `generate_json`:

```python
from pydantic import BaseModel
from essarion_build import Context, generate_json

class ReviewFinding(BaseModel):
    file: str
    line: int
    severity: str  # "info" | "warning" | "error"
    description: str
    suggested_fix: str

parsed, gen = generate_json(
    "review src/auth.py for a single finding",
    schema=ReviewFinding,
    context=Context().with_skill("code_review"),
)
finding = ReviewFinding(**parsed)
print(finding.severity, finding.suggested_fix)
```

If the model emits invalid JSON (or fails Pydantic validation), the
runtime automatically reframes the task with the validation error and
asks once more. After the second failure, `SchemaValidationError` is
raised with the last output for inspection.

Pass a raw JSON schema dict if you don't want Pydantic in the mix:

```python
parsed, gen = generate_json("…", schema={"type": "object", "required": ["a", "b"]}, …)
```

Async sibling: `agenerate_json(...)`.

## Compaction

When your Context exceeds the token budget:

```python
from essarion_build import Context, compact, truncate_files, keep_only_files

ctx = Context().with_all_skills().add_repo("./src")
print(ctx.estimate_tokens())              # e.g. 380_000

# Drop low-signal sections (repo files first, then docs) to fit a budget.
ctx = compact(ctx, max_tokens=40_000)

# Or cap each file body individually with a truncation marker.
ctx = truncate_files(ctx, max_chars_per_file=4_000)

# Or filter the file set by glob.
ctx = keep_only_files(ctx, patterns=["src/auth/*", "src/billing/*"])
```

`compact()` never drops skills, notes, or diffs — they are the
high-signal content.

## Evals

A model-driven SDK without evals is a benchmark waiting to regress.
`essarion_build.evals` is a thin harness for running a labeled benchmark
against any callable runner:

```python
from essarion_build.evals import EvalCase, contains_all, run_eval
from essarion_build import Context, reason

CASES = [
    EvalCase(task="audit JWT alg=none confusion", expected="whitelist, alg=none"),
    EvalCase(task="audit a SQL injection",        expected="parameterized, prepared"),
]

def runner(task: str):
    r = reason(task, context=Context().with_skill("secure_coding"))
    return r.plan, r.usage    # tuple → usage flows into the report

report = run_eval(CASES, runner, contains_all, name="security-v1")
print(report.summary())       # → "security-v1: 2/2 passed (100%, mean 1.00). Tokens: …"

# Compare against a baseline for CI gating
delta = report.delta(baseline_report)
if delta["regressed"]:
    raise SystemExit(f"Regressions: {delta['regressed']}")
```

Built-in scorers: `exact_match`, `contains_all`, `keyword_overlap`.
Roll your own — it's just a function returning `Score`.

## Tools (model-side)

`essarion_build` ships a small, opt-in tool surface that works on every
provider (no native tool-use required):

```python
from essarion_build import register_tool, run_tools_in_plan, Context, tool_manifest

@register_tool("read_file", description="read a file from disk")
def _read(path: str) -> str:
    return open(path).read()

ctx = Context().with_all_skills().add_note(tool_manifest())

# The model emits <tool_call name='read_file'>{"path": "…"}</tool_call>;
# you evaluate them before the next turn:
plan_with_results = run_tools_in_plan(plan_text, allow={"read_file"})
```

The `allow` set is a security boundary — unknown or disallowed tools
become inline `<tool_result error="true">…</tool_result>` instead of
running. Use this for the small-tool case (look up the schema, fetch a
URL); for full agent loops, build directly on `Provider.complete()`.

## CLI

The package installs an `essarion-build` console command. Useful for one-off coding tasks, CI scripts, and editor integrations:

```bash
# List bundled skills
essarion-build skills

# Print a skill's body
essarion-build skills --show secure_coding

# List recognized providers
essarion-build providers

# List bundled workflows
essarion-build workflows

# Estimate token cost of a context before sending
essarion-build estimate --repo ./ --json

# Run a reason() loop
essarion-build reason "review the auth flow" --repo ./src --json

# Stream a generate() loop's output
essarion-build generate "write a JWT validator" --repo ./src --stream

# Pipe a task from stdin
git diff main | essarion-build reason "review this change" -
```

## Testing your essarion-build code

Wire `StubProvider` in for deterministic, no-network tests of your own workflows:

```python
from essarion_build import Context, LiteRuntime, StubProvider, reason

def test_my_workflow():
    stub = StubProvider(responses=[
        "<plan>1</plan><tradeoffs>-</tradeoffs><verdict>ship</verdict>",
        "<verdict>ship</verdict>",
    ])
    r = reason("anything", context=Context(), _runtime=LiteRuntime(stub))
    assert "ship" in r.verdict
    assert stub.call_count == 2
```

Async sibling: `AsyncStubProvider` + `AsyncLiteRuntime`. See `essarion_build.testing` for helpers.

## Error handling

Provider failures map to typed exceptions all rooted at `EssarionError`:

| Exception | When |
|---|---|
| `ProviderAuthError` | HTTP 401/403 (bad or missing key) |
| `ProviderRateLimitError` | HTTP 429 after exhausting retries |
| `ProviderHTTPError` | Other non-2xx, or network errors after retries |
| `ProviderResponseError` | Provider returned 2xx but the body was unparseable |
| `ReasoningFormatError` | Model output still missing required tags after one repair pass |
| `CloudRuntimeNotAvailable` | `runtime="cloud"` requested (not yet shipped) |
| `ProviderNotAvailable` | Unknown provider name |
| `ContextError` | Bad input to a `Context` method |

Transient HTTP errors (429, 5xx, connection errors) get up to 2 retries with exponential backoff before surfacing.

## Lite vs Cloud

Both runtimes implement the same protocol:

| Runtime | What it does | Status in v0.3 |
|---|---|---|
| `LiteRuntime` (default) | Drives the 3-step reasoning loop locally via your provider key. Fast to set up. | **Available** |
| `CloudRuntime` | Sends the task to `build.essarion.com` for a heavier reasoning loop, longer context, and real Sourcipedia grounding. | **Stub** — raises `CloudRuntimeNotAvailable` |

```python
generate("...", runtime="cloud")           # raises in v0
essarion_build.configure(runtime="cloud")  # configure now, callable when Cloud ships
```

## Interop hooks (stubs in v0.3)

These exist on `Context` so the API surface is right; implementations land when upstream APIs are exposed.

```python
ctx.add_sourcipedia_topic("jwt")     # placeholder source entry
ctx.add_agent_skill("auth_review")   # Anthropic Agents skill manifest reference
```

```python
from essarion_build.auth import from_platform_api   # raises NotImplementedError in v0
```

## Out of scope for v0.3

No plugin loader (custom providers + custom skills cover the same surface), no embeddings/RAG (use the `Context.add_repo(include=...)` filter), no telemetry, no model-side tool use.

## License

Apache-2.0.
