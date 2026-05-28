# essarion-build

A **BYOK reasoning amplification SDK + CLI coding agent**, by Essarion. Bring your own model provider; `essarion-build` provides the reasoning loop, the grounding context, the bundled software-development skills, and the structured outputs. The CLI agent gives you an interactive, plan-first coding experience powered by the same SDK.

`essarion-build` is not a wrapper for any single LLM. It is a deliberate **plan → draft → self-check** pipeline that turns *whatever model you wire in* into a more thoughtful coder. The default is tuned to amplify **cheap** models — making a small, fast GPT reason about coding the way a senior engineer would, while spending a fraction of the tokens of a single-shot generation from a bigger model.

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

## The `essarion` CLI coding agent

Type `essarion` to launch the interactive coding agent. It uses the same SDK
under the hood — the agent IS the SDK, dressed in a TUI:

```bash
$ essarion

  essarion build · CLI coding agent
  by Essarion · amplifies any LLM with senior-engineer reasoning

  session   20260528-195838-5e4b
  cwd       /home/you/work/myproject
  model     openrouter/openai/gpt-4o-mini
  budget    $0.000 / $1.00
  skills    54 bundled, picker mode auto

  type your task to begin · /help for commands · /quit to exit
  ────────────────────────────────────────────────────────────

you: review src/auth.py for JWT alg=none confusion

  skills: auth_security web_security secure_coding scope_discipline error_handling
  auto-loaded: src/auth.py

  ── plan ──
  ┌──────────────────────────────────────────────────────────────┐
  │ plan                                                         │
  │  1. Verify the JWT lib's alg=none handling                   │
  │  2. Add an explicit allow-list of allowed algorithms         │
  │  3. Reject tokens whose alg header is missing                │
  │                                                              │
  │ tradeoffs                                                    │
  │  • chosen: whitelist (HS256 only) — closes alg=none family   │
  │  • rejected: blacklist — every new algorithm becomes risky   │
  │                                                              │
  │ verdict                                                      │
  │  do not ship without resolving step 2                        │
  └──────────────────────────────────────────────────────────────┘

  approve plan? (Enter=approve, e=edit, s=skip-to-draft, c=cancel) _
```

### Why use the agent (over Claude Code / Codex / Aider / Cursor)

1. **Plan-first interactivity.** You see the plan and verdict BEFORE the
   draft is paid for. Edit it, reject it, or send it back. No other agent
   does this — most jump straight to writing code.
2. **Live token-budget meter.** Every session has a configurable USD
   budget. The footer shows what you've spent in real time. Lets you SEE
   the savings of cheap-model amplification.
3. **Smart skill selection.** The 54 bundled skills aren't all loaded
   every turn — a fast keyword picker chooses the 3-5 most relevant
   ones. Big context savings on every call.
4. **Multi-model arbitrage.** Plan + selfcheck on a cheap model;
   `--escalate <bigger-model>` only kicks in if selfcheck rejects.
   Cheap by default, smart when it matters.
5. **Reasoning-trace persistence.** Every session saved to
   `~/.essarion/sessions/`. Replay, fork, share with a teammate.
6. **The whole SDK is yours.** Anything you can do in the agent, you can
   do in code — same `reason()`, `generate()`, `Conversation` calls.

### Quick commands

```bash
essarion                                  # interactive REPL
essarion --task "review src/auth.py"      # one-shot non-interactive
essarion --provider anthropic --model claude-sonnet-4-6
essarion --budget 5.00 --escalate claude-sonnet-4-6   # cheap+escalate
essarion --resume 20260528-195838-5e4b    # continue a saved session
essarion --skills all                     # load every skill (vs auto)

# Subcommands fall through to the original CLI
essarion skills                           # list bundled skills
essarion providers
essarion reason "task" --json
essarion generate "task" --stream
```

### Project folders

Run `essarion init` inside a repo and you'll get a `.essarion/`
directory with:

- `config.toml` — per-project defaults (provider, model, budget, skills mode)
- `sessions/` — saved sessions live with the project instead of in `~`
- `.gitignore` — keeps sessions out of git

Once initialized, any time you launch `essarion` from anywhere inside
the project tree, the agent walks up to the project root, anchors the
sandbox there, and loads `.essarion/config.toml`. No `.essarion/`?
The agent still finds the project root via `.git/`, `pyproject.toml`,
`package.json`, `Cargo.toml`, `go.mod`, etc., and falls back to
`~/.essarion/sessions/` for storage.

### Background tasks

Long-running commands shouldn't block the agent. Start them in the
background and they run in parallel while you keep planning:

```text
you: /bg npm run dev
  started [a3f9c1] pid=14852 · npm run dev

you: /bg pytest -q
  started [b7e221] pid=14855 · pytest -q

you: /bg
                  background tasks
  ┏━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━┓
  ┃ id     ┃ status  ┃ name        ┃ elapsed ┃ exit ┃
  ┡━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━┩
  │ a3f9c1 │ running │ npm run dev │   12.4s │      │
  │ b7e221 │ done    │ pytest -q   │    4.7s │    0 │
  └────────┴─────────┴─────────────┴─────────┴──────┘

you: review src/auth.py
  ── plan ──
  …(plan as normal while npm run dev keeps serving)…

  [bg] [b7e221] pytest -q → done (exit 0, 4.7s)   ← notice flushes here
```

- `/bg <cmd>` — start one
- `/bg detached <cmd>` — start one that survives `/quit`
- `/bg` — list every task with status
- `/bg show <id>` — recent stdout/stderr
- `/bg wait <id> [seconds]` — block until done
- `/bg kill <id>` — terminate
- `/bg clear` — forget finished tasks

The same tools are registered with the SDK's tool registry, so the
model can call `start_background` / `check_background` /
`wait_background` / `kill_background` / `list_background` itself
during reasoning. The footer always shows `bg N running` when tasks
are alive; completion notices print between turns; `/quit` cleanly
kills every non-detached task (SIGTERM → grace → SIGKILL via process
group, so dev-server children die too).

### Slash commands (inside the REPL)

| Command | Description |
|---|---|
| `/help` | show all commands |
| `/budget [N]` | show or set USD budget |
| `/model <p>/<m>` | switch provider/model mid-session |
| `/escalate <m>` | set escalation model (cheap → strong on reject) |
| `/skills [auto\|all\|none]` | switch picker mode |
| `/cd <path>` | change sandbox directory |
| `/history` | list this session's turns |
| `/save` | persist session (per-project or `~`) |
| `/load` | list saved sessions |
| `/bg [...]` | manage background tasks |
| `/yolo` | toggle auto-approval of side-effect tools |
| `/quit` | exit (also saves, kills non-detached bg tasks) |

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
      .with_all_skills()                 # 54 bundled coding-practice skills
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

## Recipes

For the most common asks, skip prompt engineering — pull a recipe:

```python
from essarion_build import Context, recipes, reason

task, skills = recipes.audit_for_race_conditions("the booking flow")
ctx = Context().with_skills(skills).add_repo("./src/booking")
r = reason(task, context=ctx)
```

Recipes ship for: race conditions, N+1 queries, type-annotation passes,
runbooks, API design, data migrations, hot-path optimization, endpoint
hardening, schema design. See `essarion_build.recipes.list_recipes()`.

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
