# essarion-build

A **BYOK reasoning amplification SDK** for coding tasks. Bring your own model provider; `essarion_build` provides the reasoning loop, the grounding context, the bundled software-development skills, and the structured outputs.

`essarion_build` is not a wrapper for any single LLM. It is a deliberate **plan → draft → self-check** pipeline that turns *whatever model you wire in* into a more thoughtful coder. The default is tuned to amplify **cheap** models — making a small, fast GPT reason about coding the way a senior engineer would.

## Install

```bash
pip install essarion-build
```

Set your provider key. The default is OpenRouter, which gives you access to ~any model through one API:

```bash
export OPENROUTER_API_KEY=sk-or-...
```

Or use Anthropic directly:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

## Quick start

```python
from essarion_build import Context, reason, generate

ctx = (
    Context()
      .with_all_skills()                 # 21 bundled coding-practice skills
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
from essarion_build import Context, list_skills

list_skills()
# ['api_design', 'auth_security', 'cli_design', 'code_review', 'concurrency',
#  'database_design', 'data_modeling', 'debugging', 'dependency_management',
#  'documentation', 'error_handling', 'git_workflow', 'logging',
#  'observability', 'performance', 'python_idioms', 'refactoring',
#  'scope_discipline', 'secure_coding', 'testing', 'typescript_idioms']

# Pick the ones relevant to your task...
ctx = Context().with_skills(["secure_coding", "auth_security", "error_handling"])

# ...or load them all (recommended default for coding tasks)
ctx = Context().with_all_skills()
```

Each skill is a short, actionable brief. `secure_coding` covers input validation, output encoding, secret handling, and crypto defaults. `scope_discipline` covers staying within scope. `testing` covers what to test and how. The full set is bundled with the package; no network calls.

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

Or set the budget globally:

```python
import essarion_build
essarion_build.configure(max_tokens=2000)
```

The runtime divides the budget across the 2 calls (`reason`) or 3 calls (`generate`) in the loop, plus any one-shot tag-repair retries (see below). Usage from those retries is included in the total.

## Cheap-model survival kit

Small models drop XML tags. When the model returns a selfcheck without the `<defense>` tag, the runtime asks once for just the missing tag(s) and merges the result. If even the repair pass fails, you get a typed `ReasoningFormatError` — not a silently empty `defense` field.

You don't have to opt in; this happens automatically inside `LiteRuntime`.

## The `@reasoned` decorator

Mark functions you want the future `essarion-build` CLI to enumerate. In normal Python execution the original body runs unchanged — the decorator just records the function in a module-level registry.

```python
from essarion_build import reasoned

@reasoned(context=ctx)
def parse_jwt(token: str) -> Claims:
    """Parse a JWT and return validated claims."""
    ...  # body is yours; the CLI uses this entry for future reason+generate runs
```

## BYOK and providers

The Provider seam keeps `essarion_build` model-agnostic. v0 ships two concrete providers; the model you run is your choice:

| Provider | Env var | Default model | Notes |
|---|---|---|---|
| `openrouter` (default) | `OPENROUTER_API_KEY` | `openai/gpt-4o-mini` | Routes to ~any model behind one OpenAI-compatible API. The cheap-default story. |
| `anthropic` | `ANTHROPIC_API_KEY` | (provide one, e.g. `claude-sonnet-4-6`) | Direct to the Claude API. Uses prompt caching on the system block. |

Switch globally or per-call:

```python
import essarion_build

# Stay on OpenRouter but use a stronger model
essarion_build.configure(model="anthropic/claude-sonnet-4.6")  # OpenRouter slug

# Or switch provider entirely
essarion_build.configure(provider="anthropic", model="claude-sonnet-4-6")

# Or per-call
generate("...", provider="anthropic", model="claude-sonnet-4-6", max_tokens=1500)
```

Asking for a provider that isn't shipped raises `ProviderNotAvailable`. v0.2 will add Gemini, local-OSS via Ollama, etc.

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

| Runtime | What it does | Status in v0 |
|---|---|---|
| `LiteRuntime` (default) | Drives the 3-step reasoning loop locally via your provider key. Fast to set up. | **Available** |
| `CloudRuntime` | Sends the task to `build.essarion.com` for a heavier reasoning loop, longer context, and real Sourcipedia grounding. | **Stub** — raises `CloudRuntimeNotAvailable` |

```python
generate("...", runtime="cloud")           # raises in v0
essarion_build.configure(runtime="cloud")  # configure now, callable when Cloud ships
```

## Interop hooks (stubs in v0)

These exist on `Context` so the API surface is right; implementations land when upstream APIs are exposed.

```python
ctx.add_sourcipedia_topic("jwt")     # placeholder source entry
ctx.add_agent_skill("auth_review")   # Anthropic Agents skill manifest reference
```

```python
from essarion_build.auth import from_platform_api   # raises NotImplementedError in v0
```

## Out of scope for v0

No CLI binary, no async API, no plugin loader, no embeddings/RAG, no streaming, no model-side tool use, no telemetry. We add those when there's demand.

## License

Apache-2.0.
